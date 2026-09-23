"""Entradas de medidas com formatos e larguras consistentes."""
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox, QSizePolicy, QWidget, QHBoxLayout, QLabel


def compact(field):
    locale = QLocale(QLocale.Language.Portuguese, QLocale.Country.Portugal)
    locale.setNumberOptions(QLocale.NumberOption.OmitGroupSeparator | QLocale.NumberOption.RejectGroupSeparator)
    field.setLocale(locale)
    field.setGroupSeparatorShown(False)
    # sizeHint do Qt inclui algarismos, unidade, setas, fonte e escala do ecrã.
    field.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return field


class MetresSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 99999)
        self.setSuffix(' m')
        compact(self)


class DegreesSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 359)
        self.setWrapping(True)
        self.setSuffix('º')
        compact(self)

    def textFromValue(self, value):
        return f'{value:03d}'


class KilometresSpinBox(QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(1)
        self.setRange(0, 99.9)
        self.setSingleStep(.1)
        self.setSuffix(' km')
        compact(self)


def labelled_field(text, field):
    pair = QWidget()
    row = QHBoxLayout(pair)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    label = QLabel(text)
    label.setBuddy(field)
    row.addWidget(label)
    row.addWidget(field)
    pair.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return pair
