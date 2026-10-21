import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

ColumnLayout {
    id: browser
    required property QtObject controller
    spacing: 12

    Shortcut {
        sequences: [StandardKey.Find]
        onActivated: searchField.forceActiveFocus()
    }
    FolderDialog {
        id: exportDialog
        objectName: "exportDialog"
        title: "Select a Rekordbox USB root"
        onAccepted: browser.controller.openExport(selectedFolder.toString(), formatSelector.currentValue)
    }
    Shortcut {
        sequence: "Ctrl+1"
        enabled: browser.controller.trackView
        onActivated: browser.controller.loadTrack(0, browser.controller.trackIdAt(trackList.currentIndex))
    }
    Shortcut {
        sequence: "Ctrl+2"
        enabled: browser.controller.trackView
        onActivated: browser.controller.loadTrack(1, browser.controller.trackIdAt(trackList.currentIndex))
    }
    RowLayout {
        Layout.fillWidth: true
        visible: browser.controller.linkEnabled
        ComboBox {
            objectName: "sourceSelector"
            Layout.preferredWidth: 270
            textRole: "name"
            valueRole: "key"
            model: browser.controller.sources
            currentIndex: browser.controller.selectedSourceIndex
            Accessible.name: "Music source"
            onActivated: browser.controller.selectSource(currentValue)
        }
        Text {
            text: browser.controller.linkStatus
            color: "#a9b8c3"
            Layout.fillWidth: true
            elide: Text.ElideRight
            font.pixelSize: 12
        }
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 10
        ActionButton {
            objectName: "openExport"
            text: "Open USB…"
            onClicked: exportDialog.open()
        }
        ComboBox {
            id: formatSelector
            enabled: !browser.controller.linkEnabled || browser.controller.localSource
            objectName: "formatSelector"
            Layout.preferredWidth: 155
            palette.button: "#242b30"
            palette.buttonText: "#e7e1d7"
            palette.base: "#1a2025"
            palette.text: "#e7e1d7"
            palette.highlight: "#6d543e"
            palette.highlightedText: "#ffffff"
            textRole: "label"
            valueRole: "value"
            model: [
                { label: "Auto", value: "auto" },
                { label: "Device Library", value: "pdb" },
                { label: "OneLibrary", value: "onelibrary" }
            ]
            Accessible.name: "Export format"
            onActivated: browser.controller.changeFormat(currentValue)
        }
        ActionButton {
            objectName: "refreshExport"
            text: "Refresh"
            enabled: !browser.controller.isDemo && !browser.controller.importing
            onClicked: browser.controller.refreshExport()
        }
        Text {
            text: browser.controller.importing ? "Reading library…" : browser.controller.libraryName
            color: "#a9b8c3"
            Layout.fillWidth: true
            elide: Text.ElideMiddle
            font.pixelSize: 12
        }
        BusyIndicator {
            running: browser.controller.importing
            visible: running
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
        }
        ActionButton {
            objectName: "cancelImport"
            text: "Cancel"
            visible: browser.controller.canCancelImport
            onClicked: browser.controller.cancelImport()
        }
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        Repeater {
            model: [
                { key: "tracks", label: "All tracks" },
                { key: "playlists", label: "Playlists" },
                { key: "artists", label: "Artist" },
                { key: "albums", label: "Album" },
                { key: "genres", label: "Genre" },
                { key: "bpm", label: "BPM" },
                { key: "keys", label: "Key" }
            ]
            ActionButton {
                required property var modelData
                objectName: "browse_" + modelData.key
                text: modelData.label
                Layout.fillWidth: true
                accent: browser.controller.category === modelData.key ? "#eeae75" : "#91a0ab"
                onClicked: browser.controller.browseCategory(modelData.key)
            }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        ActionButton {
            objectName: "browseBack"
            text: "‹ Back"
            visible: browser.controller.canGoBack
            onClicked: browser.controller.goBack()
        }
        Text {
            text: browser.controller.browsePath
            Layout.fillWidth: true
            elide: Text.ElideRight
            color: "#f0ebe3"
            font.pixelSize: 21
            font.weight: Font.DemiBold
        }
        Text {
            text: browser.controller.trackView
                ? browser.controller.trackCount + " / " + browser.controller.totalTracks + " tracks"
                : browser.controller.browseEntries.length + " items"
            color: "#85949e"
            font.pixelSize: 12
            Layout.leftMargin: 6
        }
        Item { Layout.fillWidth: true }
        TextField {
            id: searchField
            objectName: "searchField"
            Layout.preferredWidth: Math.min(330, browser.width * 0.38)
            Layout.preferredHeight: 42
            text: browser.controller.query
            placeholderText: browser.controller.trackView ? "Search title or artist" : "Search this category"
            placeholderTextColor: "#87959f"
            color: "#f0ebe3"
            selectionColor: "#7d5739"
            selectedTextColor: "#ffffff"
            leftPadding: 14
            rightPadding: clearSearch.visible ? 42 : 14
            onTextChanged: browser.controller.query = text
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
            visible: browser.controller.trackView
            model: browser.controller.libraryModel
            keyNavigationEnabled: true
            highlightFollowsCurrentItem: true
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
                required property string detail
                required property string unavailableReason
                width: trackList.width
                height: 68
                border.color: trackList.currentIndex === index ? "#9e7958" : "transparent"
                border.width: 1
                color: index % 2 === 0 ? "#1a2025" : "#1e252b"
                MouseArea {
                    anchors.fill: parent
                    onClicked: { trackList.currentIndex = row.index; trackList.forceActiveFocus() }
                }
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
                            text: row.artist + (row.available ? "" : " · " + (row.unavailableReason || "Unavailable demo track"))
                            color: "#8998a3"
                            font.pixelSize: 12
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                    }
                    Text {
                        text: row.detail
                        color: "#8998a3"
                        Layout.maximumWidth: 200
                        elide: Text.ElideRight
                        visible: browser.width > 1000
                        font.pixelSize: 11
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
                        enabled: browser.controller.decks[0].canLoad && (row.available || browser.controller.isDemo)
                        onClicked: browser.controller.loadTrack(0, row.trackId)
                        Accessible.name: "Load " + row.trackTitle + " on deck A"
                    }
                    ActionButton {
                        objectName: "loadB_" + row.trackId
                        text: "Load B"
                        accent: "#93c9c7"
                        enabled: browser.controller.decks[1].canLoad && (row.available || browser.controller.isDemo)
                        onClicked: browser.controller.loadTrack(1, row.trackId)
                        Accessible.name: "Load " + row.trackTitle + " on deck B"
                    }
                }
            }
        }
        ListView {
            id: categoryList
            objectName: "categoryList"
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            visible: !browser.controller.trackView
            model: browser.controller.browseEntries
            keyNavigationEnabled: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Keys.onReturnPressed: {
                if (currentIndex >= 0 && currentIndex < count)
                    browser.controller.openEntry(model[currentIndex].entryId)
            }
            Keys.onLeftPressed: browser.controller.goBack()
            delegate: ItemDelegate {
                id: groupRow
                required property var modelData
                required property int index
                objectName: "entry_" + modelData.entryId
                width: categoryList.width
                height: 58
                onClicked: browser.controller.openEntry(modelData.entryId)
                background: Rectangle {
                    color: groupRow.hovered || categoryList.currentIndex === groupRow.index
                           ? "#303b44" : (groupRow.index % 2 === 0 ? "#1a2025" : "#1e252b")
                }
                contentItem: RowLayout {
                    spacing: 16
                    Text { text: "›"; color: "#eeae75"; font.pixelSize: 24 }
                    Text {
                        text: groupRow.modelData.name
                        color: "#e9e4dd"
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                    }
                    Text { text: groupRow.modelData.detail; color: "#8998a3"; font.pixelSize: 12 }
                }
            }
        }
        Column {
            anchors.centerIn: parent
            spacing: 10
            visible: browser.controller.trackView ? browser.controller.trackCount === 0 : browser.controller.browseEntries.length === 0
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: browser.controller.trackView ? "No matching tracks" : "No matching items"
                color: "#e9e4dd"
                font.pixelSize: 18
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: browser.controller.query.length ? "Try another search." : "This view is empty."
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
}
