import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: card
    required property var controller
    required property int deckIndex
    required property var deckState
    property color accent: deckIndex === 0 ? "#eeae75" : "#93c9c7"
    property string deckName: deckIndex === 0 ? "A" : "B"
    color: "#1c2227"
    radius: 12
    border.color: "#323b42"
    implicitHeight: 252

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 13
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "DECK " + card.deckName
                color: card.accent
                font.pixelSize: 12
                font.weight: Font.Bold
                font.letterSpacing: 1.5
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                Layout.preferredWidth: statusText.implicitWidth + 18
                Layout.preferredHeight: 24
                radius: 12
                color: card.deckState.playing ? card.accent : "#30383e"
                Text {
                    id: statusText
                    anchors.centerIn: parent
                    text: card.deckState.status
                    color: card.deckState.playing ? "#121619" : "#b7c0c6"
                    font.pixelSize: 11
                    font.weight: Font.Medium
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            CoverArt {
                artwork: card.deckState.artwork
                Layout.preferredWidth: 68
                Layout.preferredHeight: 68
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                Text {
                    text: card.deckState.title
                    color: "#f0ebe3"
                    font.pixelSize: 19
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                Text {
                    text: card.deckState.artist
                    color: "#99a6af"
                    font.pixelSize: 12
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            Rectangle {
                Layout.fillWidth: true
                height: 3
                radius: 1.5
                color: "#3b444c"
                Rectangle {
                    width: parent.width * card.deckState.progress
                    height: parent.height
                    radius: parent.radius
                    color: card.accent
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Text { text: card.deckState.elapsed; color: "#aeb8be"; font.pixelSize: 11 }
                Item { Layout.fillWidth: true }
                Text { text: "−" + card.deckState.remaining; color: "#77858f"; font.pixelSize: 11 }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            ActionButton {
                objectName: "play" + card.deckName
                text: card.deckState.playing ? "Pause" : "Play"
                accent: card.accent
                filled: true
                enabled: card.deckState.canPlay
                onClicked: card.controller.togglePlayback(card.deckIndex)
                Accessible.name: text + " deck " + card.deckName
            }
            ActionButton {
                objectName: "unload" + card.deckName
                text: "Unload"
                enabled: card.deckState.canUnload
                onClicked: card.controller.unload(card.deckIndex)
                Accessible.name: "Unload deck " + card.deckName
            }
            Item { Layout.fillWidth: true }
            Text {
                visible: card.deckState.status === "Loading"
                text: "Loading…"
                color: "#99a6af"
                font.pixelSize: 12
            }
        }
        Text {
            text: card.deckState.error
            visible: text.length > 0
            color: "#efae9d"
            font.pixelSize: 11
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }
    }
}
