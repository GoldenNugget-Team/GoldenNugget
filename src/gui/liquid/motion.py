from PySide6.QtCore import QEasingCurve, QVariantAnimation
from PySide6.QtWidgets import QApplication


def animate(owner, start, end, update, *, duration=300, finished=None, easing=QEasingCurve.OutCubic):
    animations = getattr(owner, '_liquid_animations', None)
    if animations is None:
        animations = owner._liquid_animations = set()
    animation = QVariantAnimation(owner)
    animation.setStartValue(start)
    animation.setEndValue(end)
    app = QApplication.instance()
    animation.setDuration(0 if app and app.property("liquid_reduce_motion") else duration)
    animation.setEasingCurve(easing)
    animation.valueChanged.connect(update)
    animations.add(animation)

    def complete():
        animations.discard(animation)
        if finished:
            finished()
        animation.deleteLater()

    animation.finished.connect(complete)
    animation.start()
    return animation
