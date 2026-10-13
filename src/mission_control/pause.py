"""Bounded control requests for one acknowledged turn; ACK is not termination."""
import time
from .rpc import RpcError, ConnectionLost

CHECKPOINT_INSTRUCTION = (
    'Mission Control requests a safe pause. Finish only the current small step, '
    'do not start new operations. Report completed actions, uncertain outcomes '
    'and the exact next step so this mission can continue safely. Do not repeat '
    'actions or start background work. End this turn promptly.')


class TurnControl:
    def __init__(self,adapter,thread_id,turn_id,model,*,stop_requested=None,
                 receipt=None,clock=time.monotonic,grace=5,active_target=None):
        if any(not isinstance(v,str) or not v for v in (thread_id,turn_id,model)):
            raise ValueError('Acknowledged thread, turn and model IDs required')
        self.adapter=adapter;self.thread_id=thread_id;self.turn_id=turn_id;self.model=model
        self.stop_requested=stop_requested or (lambda:False);self.receipt=receipt or (lambda value:None)
        self.clock=clock;self.grace=grace;self.next_check=0;self.deadline=None
        self.reason=None;self.steered=False;self.interrupted=False
        self.confirm_by=None
        self.active_target=active_target

    def record(self,phase,*,error=None):
        value={'threadId':self.thread_id,'turnId':self.turn_id,'reason':self.reason,
               'phase':phase,'terminalConfirmed':False,'at':time.time()}
        if isinstance(error,RpcError):
            value['failure']={'kind':'rpc_rejected','code':error.code if type(error.code) is int else None}
        elif isinstance(error,TimeoutError):value['failure']={'kind':'timeout_outcome_unknown'}
        elif isinstance(error,ConnectionLost):value['failure']={'kind':'connection_lost_outcome_unknown'}
        self.receipt(value)

    async def _active_target(self):
        # The live adapter binds this to the exact acknowledged ID and lifecycle
        # events. Active rollout hydration may be unavailable before persistence.
        # Server expectedTurnId/turnId checks still reject stale control requests.
        if self.active_target is not None:return self.active_target() is True
        thread=await self.adapter.read_thread(self.thread_id)
        active=[t for t in thread.get('turns',[]) if t.get('status')=='inProgress']
        return thread.get('id')==self.thread_id and len(active)==1 and active[0].get('id')==self.turn_id

    async def tick(self):
        now=self.clock()
        if self.reason is None:
            if self.stop_requested():self.reason='user_pause'
            elif now>=self.next_check:
                self.next_check=now+5
                gate=await self.adapter.credit_gate(self.model)
                if not gate['allowed']:self.reason=gate['reason']
        if self.reason is None:return
        if not self.steered:
            if not await self._active_target():return
            self.steered=True;self.deadline=now+self.grace
            self.record('steer_requested')  # Durable before RPC; never blindly repeat.
            try:
                response=await self.adapter.rpc.request('turn/steer',{
                    'threadId':self.thread_id,'expectedTurnId':self.turn_id,
                    'input':[{'type':'text','text':CHECKPOINT_INSTRUCTION}]},timeout=3)
                self.record('steer_acknowledged' if response.get('turnId')==self.turn_id else 'steer_mismatch')
            except (RpcError,TimeoutError) as error:
                self.record('steer_unavailable_or_unknown',error=error);self.deadline=self.clock()
            except ConnectionLost as error:
                self.record('steer_unavailable_or_unknown',error=error);raise
        if not self.interrupted and self.clock()>=self.deadline:
            if not await self._active_target():return
            self.interrupted=True;self.record('interrupt_requested')
            self.confirm_by=self.clock()+10
            try:
                await self.adapter.rpc.request('turn/interrupt',{
                    'threadId':self.thread_id,'turnId':self.turn_id},timeout=3)
                self.record('interrupt_acknowledged')
            except (RpcError,TimeoutError) as error:self.record('interrupt_unavailable_or_unknown',error=error)
            except ConnectionLost as error:
                self.record('interrupt_unavailable_or_unknown',error=error);raise
