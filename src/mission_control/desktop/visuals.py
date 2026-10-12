"""Lightweight native visuals. Only real snapshots cause bounded motion."""
from .i18n import tr, display, join_text, format_text, format_value, enum_label, message_text
from .localized_widgets import QWidget, QPushButton, set_text
import math
from PySide6.QtCore import Qt,QPointF,QRectF,Property,QPropertyAnimation,QEasingCurve,QAbstractAnimation,Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient, QPainterPath, QFont
from PySide6.QtWidgets import QApplication, QSizePolicy
from .theme import tokens


def animation(target,property,start,end,duration=260):
    result=QPropertyAnimation(target,property,target);result.setStartValue(start);result.setEndValue(end)
    result.setDuration(duration);result.setEasingCurve(QEasingCurve.OutCubic);return result


def alpha(value,amount):
    result=QColor(value);result.setAlphaF(amount);return result


class MissionBackdrop(QWidget):
    def paintEvent(self,event):
        p=tokens();painter=QPainter(self);painter.fillRect(self.rect(),QColor(p['bg']))
        for x,y,r,amount in ((.92,.02,330,.025),):
            gradient=QRadialGradient(self.width()*x,self.height()*y,r)
            gradient.setColorAt(0,alpha(p['accent'],amount));gradient.setColorAt(1,alpha(p['accent'],0))
            painter.fillRect(self.rect(),gradient)


class MotionButton(QPushButton):
    """Keep native button semantics; interpolate only the surface color."""
    def __init__(self,text,parent=None):
        super().__init__(text,parent);self._hover=0.;self.motion=animation(self,b'hover',0.,1.,150)
        self.setCursor(Qt.PointingHandCursor);self.setSizePolicy(QSizePolicy.Maximum,QSizePolicy.Fixed)
    def get_hover(self):return self._hover
    def set_hover(self,value):self._hover=value;self.update()
    hover=Property(float,get_hover,set_hover)
    def transition(self,end):
        self.motion.stop()
        if QApplication.instance().property('reducedMotion'):self.hover=end
        else:self.motion.setStartValue(self._hover);self.motion.setEndValue(end);self.motion.start()
    def enterEvent(self,event):self.transition(1.);super().enterEvent(event)
    def leaveEvent(self,event):self.transition(0.);super().leaveEvent(event)
    def paintEvent(self,event):
        super().paintEvent(event)
        if self._hover and self.isEnabled():
            painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(alpha(tokens()['accent'],self._hover*.85),1.3));painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),8,8)


class RouterNetwork(QWidget):
    """The displayed nodes are catalog/decision facts, never illustrative model IDs."""
    model_inspected=Signal(str)
    def __init__(self,parent=None,compact=False):
        super().__init__(parent);self.compact=compact;self.models=[];self.selected=None;self.reason=''
        self.phase=tr('Нет активной миссии');self.effort='—';self.active=False;self.reduced_motion=False
        self._pulse=1.;self._signature=None;self.pulse=animation(self,b'activity',0.,1.,750)
        self._targets=[];self.inspected=None;self.availability={};self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(280,130 if compact else 330)
        self.setAccessibleName(tr('Сеть решений Smart Router'));self.setToolTip(tr('Модели и решения из Codex. Линии показывают выбранный маршрут.'))
    def inspect(self,identity):
        self.inspected=identity;self.model_inspected.emit(identity);self.update()
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            for identity,rect in self._targets:
                if rect.contains(event.position()):self.inspect(identity);self.setFocus();event.accept();return
        super().mousePressEvent(event)
    def keyPressEvent(self,event):
        if self.models and event.key() in (Qt.Key_Left,Qt.Key_Right,Qt.Key_Home,Qt.Key_End):
            ids=[m['model'] for m in self.models];current=ids.index(self.inspected) if self.inspected in ids else -1
            index=0 if event.key()==Qt.Key_Home else len(ids)-1 if event.key()==Qt.Key_End else (current+(1 if event.key()==Qt.Key_Right else -1))%len(ids)
            self.inspect(ids[index]);event.accept();return
        super().keyPressEvent(event)
    def get_activity(self):return self._pulse
    def set_activity(self,value):self._pulse=value;self.update()
    activity=Property(float,get_activity,set_activity)
    def set_reduced_motion(self,value):
        self.reduced_motion=bool(value)
        if value:self.pulse.stop();self.activity=1.
    def set_snapshot(self,data):
        active=next((j for j in data.get('missions',[]) if j['id']==data.get('active')),None)
        live=(active or {}).get('live',{});decision=live.get('decision') or (active or {}).get('model') or {}
        self.selected=decision.get('model');self.effort=decision.get('effort') or '—';self.reason=message_text(decision.get('reason') or '')
        catalog=list(data.get('models',[]));chosen=next((m for m in catalog if m['model']==self.selected),None)
        if self.selected and chosen is None:chosen={'model':self.selected,'displayName':self.selected}
        self.models=([chosen] if chosen else [])+[m for m in catalog if m['model']!=self.selected][:2 if chosen else 3]
        self.phase=live.get('stage') or (active or {}).get('status') or 'idle'
        self.active=bool(active and data.get('workerRunning') and self.phase in {'running','executing','validating','starting','routing','planning','ready','submitted','completed_unvalidated'})
        signature=(data.get('active'),self.selected,self.effort,self.phase,self.reason,len(live.get('attempts',[])),self.active)
        if signature!=self._signature:
            self._signature=signature
            if self.active and not self.reduced_motion:self.pulse.stop();self.pulse.start()
            else:self.pulse.stop();self.activity=1.
        self.setToolTip((self.reason or tr('Нет сохранённого решения маршрутизатора'))+'\n'+ join_text('\n', (m.get('displayName') or m['model'] for m in self.models)));self.update()
    def write(self,painter,rect,text,size=13,muted=False):
        font=QFont('Segoe UI');font.setPixelSize(size);painter.setFont(font)
        painter.setPen(QColor(tokens()['muted' if muted else 'text']))
        value=painter.fontMetrics().elidedText(str(text),Qt.ElideMiddle,int(rect.width()))
        painter.drawText(rect,Qt.AlignCenter,str(value))
    def glow(self,painter,point,radius,amount):
        gradient=QRadialGradient(point,radius);gradient.setColorAt(0,alpha(tokens()['accent'],amount));gradient.setColorAt(1,alpha(tokens()['accent'],0))
        painter.setPen(Qt.NoPen);painter.setBrush(gradient);painter.drawEllipse(point,radius,radius)
    def link(self,painter,a,b,chosen=False):
        path=QPainterPath(a);dx=(b.x()-a.x())*.5;path.cubicTo(a+QPointF(dx,0),b-QPointF(dx,0),b)
        painter.setPen(QPen(alpha(tokens()['accent' if chosen else 'border'],.85 if chosen else .55),2 if chosen else 1));painter.setBrush(Qt.NoBrush);painter.drawPath(path)
        if chosen and self.pulse.state()==QAbstractAnimation.Running:
            point=path.pointAtPercent(self._pulse);self.glow(painter,point,18,.45)
            painter.setPen(Qt.NoPen);painter.setBrush(QColor(tokens()['text']));painter.drawEllipse(point,3,3)
    def node(self,painter,point,radius,name,selected=False):
        if selected:self.glow(painter,point,radius*2,.18)
        painter.setPen(QPen(QColor(tokens()['accent' if selected else 'border']),1.4));painter.setBrush(alpha(tokens()['surface'],.94));painter.drawEllipse(point,radius,radius)
        self.write(painter,QRectF(point.x()-radius+3,point.y()-16,radius*2-6,32),name,17 if radius>40 else 12)
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing);w,h=self.width(),self.height()
        self._targets=[]
        core=QPointF(w*.41,h*.48);origin=QPointF(w*.10,h*.48);radius=32 if self.compact else 49
        if not self.compact:
            self.glow(painter,core,min(w,h)*.47,.10)
            painter.setPen(QPen(alpha(tokens()['border'],.25),1));painter.setBrush(Qt.NoBrush)
            for ring in (radius+21,radius+47):painter.drawEllipse(core,ring,ring)
            for x in range(15,w,38):
                for y in range(15,h,38):painter.drawPoint(x,y)
        self.link(painter,origin,core,bool(self.selected));self.node(painter,origin,24,tr('Задача'))
        self.node(painter,core,radius,tr('Выбор'),bool(self.selected))
        visible_models=(self.models[:1] if self.selected else []) if self.compact else self.models
        if visible_models:
            count=len(visible_models)
            for index,model in enumerate(visible_models):
                y=h*.48 if count==1 else h*(.10+.64*index/(count-1))
                point=QPointF(w*(.82 if index==0 else .75),y);chosen=model['model']==self.selected
                self._targets.append((model['model'],QRectF(point.x()-36,point.y()-36,72,108)))
                self.link(painter,core,point,chosen);self.node(painter,point,29,model['model'],chosen)
                if model['model']==self.inspected:
                    painter.setPen(QPen(QColor(tokens()['text']),2,Qt.DashLine));painter.setBrush(Qt.NoBrush);painter.drawEllipse(point,34,34)
                if not self.compact:
                    left=max(0,min(w-184,point.x()-92))
                    self.write(painter,QRectF(left,point.y()+33,184,20),model.get('displayName') or model['model'],12)
                    self.write(painter,QRectF(left,point.y()+52,184,20),tr('Недоступна для новой отправки') if self.availability.get(model['model']) is False else enum_label(self.effort) if chosen else tr('В каталоге'),12,True)
        else:self.write(painter,QRectF(w*.60,h*.40,w*.37,50),tr('Нет решения') if self.compact and not self.selected else tr('Каталог не получен'),13,True)
        if not self.compact:self.write(painter,QRectF(core.x()-112,core.y()+radius+12,224,24),tr('Наблюдаемый маршрут'),12,True)
        if self.hasFocus():
            painter.setPen(QPen(QColor(tokens()['accent']),2));painter.setBrush(Qt.NoBrush);painter.drawRoundedRect(QRectF(self.rect()).adjusted(2,2,-2,-2),8,8)

class QuotaTelemetry(QWidget):
    """Observed remaining percentages; labels stay exact while bars settle."""
    def __init__(self,parent=None):
        super().__init__(parent);self.windows=[];self._settle=1.;self.reduced_motion=False
        self.motion=animation(self,b'settle',0.,1.,350);self.setMinimumHeight(116)
    def get_settle(self):return self._settle
    def set_settle(self,value):self._settle=value;self.update()
    settle=Property(float,get_settle,set_settle)
    def set_data(self,data,reduced=False):
        from .widgets import limits_text
        windows=data.get('windows',[]);self.reduced_motion=reduced;self.setToolTip(limits_text(data))
        if windows!=self.windows:
            self.windows=[dict(w) for w in windows];self.motion.stop()
            if reduced:self.settle=1.
            else:self.motion.start()
        elif reduced:self.motion.stop();self.settle=1.
    def paintEvent(self,event):
        from .widgets import format_time
        painter=QPainter(self);painter.setRenderHint(QPainter.Antialiasing);font=QFont('Segoe UI');font.setPixelSize(12);painter.setFont(font)
        for index,(kind,title) in enumerate((('five_hour',tr('5 часов')),('weekly',tr('Неделя')))):
            y=index*58;w=self.width();items=[item for item in self.windows if item['kind']==kind]
            values=[item for item in items if item.get('remainingPercent') is not None and item.get('usedPercent') is not None]
            valid=bool(values) and len(values)==len(items)
            item=min(values,key=lambda i:i['remainingPercent']) if valid else {}
            remaining=item.get('remainingPercent');used=item.get('usedPercent')
            painter.setPen(QColor(tokens()['text']));painter.drawText(QRectF(0,y,w,20),Qt.AlignLeft,str(title + (tr(' · минимум') if len(items) > 1 else '')))
            painter.drawText(QRectF(0,y,w,20),Qt.AlignRight,str(format_text([format_value(remaining, -1, format_text(['g'])), tr('% осталось')]) if valid else tr('Нет данных')))
            painter.setPen(Qt.NoPen);painter.setBrush(alpha(tokens()['border'],.55));painter.drawRoundedRect(QRectF(0,y+26,w,4),2,2)
            if valid:
                painter.setBrush(QColor(tokens()['accent']));painter.drawRoundedRect(QRectF(0,y+26,w*max(0,min(100,remaining))/100*self._settle,4),2,2)
            painter.setPen(QColor(tokens()['muted']))
            painter.drawText(QRectF(0,y+35,w,18),Qt.AlignLeft,str(format_text([format_value(used, -1, format_text(['g'])), tr('% использовано')]) if valid else tr('Нет наблюдений')))
            when=format_time(item.get('resetsAt'));reset=tr('Сброс неизвестен') if item.get('resetsAt') is None else tr('Сброс ')+when
            painter.drawText(QRectF(w*.48,y+35,w*.52,18),Qt.AlignRight,str(reset))
