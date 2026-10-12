"""Project validation hooks on the durable Limit Manager state machine."""
from pathlib import Path
from .managed import ManagedRunner
from .routing import Task
from .state import state_exists, StateError
from . import validator


class ProjectRunner(ManagedRunner):
    require_checkpoint=False
    @property
    def root(self):return self.path.parent

    async def run_project(self, task, spec, *, overlays=(), **kwargs):
        if state_exists(self.path):raise StateError('Run exists; resume saved project mission')
        snapshot=validator.prepare(self.root,spec,overlays)
        if self.require_checkpoint:
            from .checkpoints import create
            create(self.root,snapshot)
        task=task if isinstance(task,Task) else Task(task,operation='code',estimated_files=len(spec['writeFiles']))
        return await super().run(task,expected='JSON file edits',validation_spec=spec,**kwargs)

    def _validate_state(self,data):
        if 'validationSpec' not in data:raise StateError('Project runner requires a project validation journal')
        super()._validate_state(data)
        if self.require_checkpoint:
            from .checkpoints import verify
            verify(self.root,validator.load_state(self.root/'snapshot.json'))
        if data['stage']=='completed':validator.verified_delta(self.root)

    def _check_validation_spec(self,spec):
        validator.check_spec(spec)
        if self.cwd!=self.root/'workspace':raise StateError('Project runner workspace differs')
        validator.prepare(self.root,spec)

    def _prompt(self,data):
        failed=[a['validation'] for a in data['attempts'] if a.get('validation',{}).get('passed') is False]
        feedback=failed[-1].get('feedback','') if failed else ''
        validator.integrity(self.root,data['validationSpec'],validator.load_state(self.root/'snapshot.json'))
        return validator.prompt(self.root,data['validationSpec'],data['task']['text'],feedback)

    async def _validation(self,data,attempt):
        return await validator.validate(self.root,data['validationSpec'],attempt['turnId'],attempt['outcome']['text'],stop_requested=self.stop_requested)
