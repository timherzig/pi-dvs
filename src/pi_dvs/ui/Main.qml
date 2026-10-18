import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    required property QtObject controller
    objectName: "mainWindow"
    visible: true
    width: 1120
    height: 980
    minimumWidth: 780
    minimumHeight: 800
    title: "pi-dvs · Library"
    color: "#121619"
    font.family: "Helvetica Neue"
    font.pixelSize: 14

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 28
        spacing: 20
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Rectangle {
                width: 30; height: 30; radius: 15
                color: "#eeae75"
                Rectangle {
                    anchors.centerIn: parent
                    width: 10; height: 10; radius: 5; color: "#121619"
                }
            }
            Text {
                text: "pi / dvs"
                color: "#f0ebe3"
                font.pixelSize: 25
                font.weight: Font.DemiBold
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "LIBRARY / TWO DECKS"
                color: "#94a2ac"
                font.pixelSize: 11
                font.letterSpacing: 2
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            Repeater {
                model: 2
                DeckCard {
                    required property int index
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    controller: window.controller
                    deckIndex: index
                    deckState: window.controller.decks[index]
                }
            }
        }
        VinylSimulator {
            Layout.fillWidth: true
            controller: window.controller
        }
        LibraryBrowser {
            Layout.fillWidth: true
            Layout.fillHeight: true
            controller: window.controller
        }
        Text {
            visible: window.controller.notice.length > 0
            text: window.controller.notice
            color: "#efae9d"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font.pixelSize: 12
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "Silent demo · playback is simulated"
                color: "#8998a3"
                font.pixelSize: 12
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "Stop the record or lift the needle to change tracks"
                color: "#687985"
                font.pixelSize: 11
            }
        }
    }
}
