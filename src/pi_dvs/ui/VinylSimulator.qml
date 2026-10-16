import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: simulator
    required property QtObject controller
    implicitHeight: 112
    color: "#182025"
    radius: 10
    border.color: "#35434c"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "SIMULATED VINYL"
                color: "#b0bec6"
                font.pixelSize: 11
                font.weight: Font.DemiBold
                font.letterSpacing: 1.3
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "Demo controls · no hardware connected"
                color: "#7f929e"
                font.pixelSize: 11
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 24
            Repeater {
                model: 2
                RowLayout {
                    id: controls
                    required property int index
                    property string deckName: index === 0 ? "A" : "B"
                    property var deckState: simulator.controller.decks[index]
                    property color accent: index === 0 ? "#eeae75" : "#93c9c7"
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    spacing: 10
                    Text {
                        text: controls.deckName
                        color: controls.accent
                        font.pixelSize: 15
                        font.weight: Font.Bold
                    }
                    ActionButton {
                        objectName: "needle" + controls.deckName
                        text: controls.deckState.needleDown ? "Lift needle" : "Lower needle"
                        accent: controls.accent
                        filled: controls.deckState.needleDown
                        Layout.fillWidth: true
                        onClicked: simulator.controller.setNeedleDown(controls.index, !controls.deckState.needleDown)
                        Accessible.name: text + " on deck " + controls.deckName
                    }
                    ActionButton {
                        objectName: "platter" + controls.deckName
                        text: controls.deckState.platterSpinning ? "Stop platter" : "Start platter"
                        accent: controls.accent
                        filled: controls.deckState.platterSpinning
                        Layout.fillWidth: true
                        onClicked: simulator.controller.setPlatterSpinning(controls.index, !controls.deckState.platterSpinning)
                        Accessible.name: text + " on deck " + controls.deckName
                    }
                }
            }
        }
    }
}
