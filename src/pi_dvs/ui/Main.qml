import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    required property QtObject controller
    objectName: "mainWindow"
    visible: true
    width: 1020
    height: 800
    minimumWidth: 780
    minimumHeight: 700
    title: "pi-dvs · Desktop demo"
    color: "#121619"
    font.family: "Helvetica Neue"
    font.pixelSize: 14

    Shortcut {
        sequences: [StandardKey.Find]
        onActivated: searchField.forceActiveFocus()
    }
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
                text: "DESKTOP DEMO"
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
        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "Library"
                color: "#f0ebe3"
                font.pixelSize: 21
                font.weight: Font.DemiBold
            }
            Text {
                text: window.controller.trackCount + " / " + window.controller.totalTracks + " tracks"
                color: "#85949e"
                font.pixelSize: 12
                Layout.leftMargin: 6
            }
            Item { Layout.fillWidth: true }
            TextField {
                id: searchField
                objectName: "searchField"
                Layout.preferredWidth: Math.min(330, window.width * 0.38)
                Layout.preferredHeight: 42
                placeholderText: "Search title or artist"
                placeholderTextColor: "#87959f"
                color: "#f0ebe3"
                selectionColor: "#7d5739"
                selectedTextColor: "#ffffff"
                leftPadding: 14
                rightPadding: clearSearch.visible ? 42 : 14
                onTextChanged: window.controller.query = text
                Keys.onEscapePressed: clear()
                background: Rectangle {
                    radius: 8
                    color: "#1c2227"
                    border.color: searchField.activeFocus ? "#eeae75" : "#38424a"
                }
                ToolButton {
                    id: clearSearch
                    objectName: "clearSearch"
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 38; height: 38
                    visible: searchField.text.length > 0
                    text: "×"
                    Accessible.name: "Clear search"
                    onClicked: searchField.clear()
                    contentItem: Text {
                        text: clearSearch.text
                        color: "#b1bec7"
                        font.pixelSize: 22
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Item {}
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 170
            color: "#1a2025"
            border.color: "#303a42"
            radius: 10
            clip: true
            ListView {
                id: trackList
                objectName: "trackList"
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                model: window.controller.libraryModel
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Rectangle {
                    id: row
                    required property int index
                    required property string trackId
                    required property string trackTitle
                    required property string artist
                    required property string duration
                    required property string artwork
                    required property bool available
                    width: trackList.width
                    height: 72
                    color: index % 2 === 0 ? "#1a2025" : "#1e252b"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 20
                        spacing: 14
                        CoverArt {
                            artwork: row.artwork
                            Layout.preferredWidth: 44
                            Layout.preferredHeight: 44
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 5
                            Text {
                                text: row.trackTitle
                                color: row.available ? "#e9e4dd" : "#aaa39b"
                                font.pixelSize: 14
                                font.weight: Font.Medium
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }
                            Text {
                                text: row.artist + (row.available ? "" : " · Unavailable demo track")
                                color: "#8998a3"
                                font.pixelSize: 12
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }
                        }
                        Text {
                            text: row.duration
                            color: "#95a3ad"
                            font.pixelSize: 12
                            Layout.rightMargin: 12
                        }
                        ActionButton {
                            objectName: "loadA_" + row.trackId
                            text: "Load A"
                            accent: "#eeae75"
                            enabled: window.controller.decks[0].canLoad
                            onClicked: window.controller.loadTrack(0, row.trackId)
                            Accessible.name: "Load " + row.trackTitle + " on deck A"
                        }
                        ActionButton {
                            objectName: "loadB_" + row.trackId
                            text: "Load B"
                            accent: "#93c9c7"
                            enabled: window.controller.decks[1].canLoad
                            onClicked: window.controller.loadTrack(1, row.trackId)
                            Accessible.name: "Load " + row.trackTitle + " on deck B"
                        }
                    }
                }
            }
            Column {
                anchors.centerIn: parent
                spacing: 10
                visible: window.controller.trackCount === 0
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "No matching tracks"
                    color: "#e9e4dd"
                    font.pixelSize: 18
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Try a different title or artist."
                    color: "#95a3ad"
                    font.pixelSize: 13
                }
                ActionButton {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Clear search"
                    onClicked: searchField.clear()
                }
            }
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
                text: "Pause a deck to replace its track"
                color: "#687985"
                font.pixelSize: 11
            }
        }
    }
}
