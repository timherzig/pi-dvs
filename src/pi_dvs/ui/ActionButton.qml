import QtQuick
import QtQuick.Controls

Button {
    id: control
    property color accent: "#e7e1d7"
    property bool filled: false
    implicitHeight: 38
    implicitWidth: Math.max(78, contentItem.implicitWidth + 28)
    hoverEnabled: true
    font.pixelSize: 13
    font.weight: Font.DemiBold
    opacity: enabled ? 1 : 0.35
    contentItem: Text {
        text: control.text
        font: control.font
        color: control.filled ? "#121619" : control.accent
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 7
        color: control.filled ? control.accent : (control.down ? "#3c4348" : control.hovered ? "#30373d" : "#242b30")
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.accent : control.filled ? control.accent : "#3b444b"
    }
}
