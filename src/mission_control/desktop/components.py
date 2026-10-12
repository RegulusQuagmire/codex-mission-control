"""Shared native Concept C surfaces with semantic state and responsive layouts."""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QBoxLayout, QGridLayout, QApplication, QGraphicsOpacityEffect
from .localized_widgets import QWidget, set_text
from .widgets import label
from .visuals import animation


def severity(widget,value):
    if widget.property('fluentSeverity')==value:return
    widget.setProperty('fluentSeverity',value)
    widget.style().unpolish(widget);widget.style().polish(widget);widget.update()


class StateBanner(QFrame):
    def __init__(self,parent=None):
        super().__init__(parent);self.setProperty('fluentRole','messageBar')
        body=QVBoxLayout(self);body.setContentsMargins(16,12,16,12);body.setSpacing(4)
        self.title=label('','section');self.detail=label('','muted')
        body.addWidget(self.title);body.addWidget(self.detail)
        self.effect=QGraphicsOpacityEffect(self);self.setGraphicsEffect(self.effect)
        self.motion=animation(self.effect,b'opacity',.72,1.,160);self._signature=None
    def set_state(self,state):
        signature=tuple(str(state[key]) for key in ('title','detail','severity'))
        set_text(self.title,'setText',state['title']);set_text(self.detail,'setText',state['detail'])
        severity(self,state['severity'])
        self.motion.stop();self.effect.setOpacity(1.)
        if signature!=self._signature and self._signature and not QApplication.instance().property('reducedMotion'):
            self.motion.start()
        self._signature=signature


class ResponsiveColumns(QWidget):
    def __init__(self,left,right,parent=None,breakpoint=820):
        super().__init__(parent);self.breakpoint=breakpoint
        self.box=QBoxLayout(QBoxLayout.LeftToRight,self);self.box.setContentsMargins(0,0,0,0);self.box.setSpacing(16)
        self.box.addWidget(left,3);self.box.addWidget(right,2)
    def resizeEvent(self,event):
        direction=QBoxLayout.TopToBottom if self.width()<self.breakpoint else QBoxLayout.LeftToRight
        if self.box.direction()!=direction:self.box.setDirection(direction)
        super().resizeEvent(event)


class MetricStrip(QFrame):
    def __init__(self,items,parent=None):
        super().__init__(parent);self.setProperty('fluentRole','metricStrip');self.values={}
        grid=QGridLayout(self);grid.setContentsMargins(16,12,16,12);grid.setHorizontalSpacing(24)
        for column,(key,title) in enumerate(items):
            value=label('0','metric');self.values[key]=value
            grid.addWidget(value,0,column);grid.addWidget(label(title,'muted'),1,column);grid.setColumnStretch(column,1)
