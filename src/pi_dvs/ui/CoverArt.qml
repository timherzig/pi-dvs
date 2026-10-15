import QtQuick

Rectangle {
    id: cover
    property string artwork: ""
    color: "#343b42"
    radius: 5
    clip: true
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.7
        height: width
        radius: width / 2
        color: "#20262b"
        border.color: "#66717b"
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.26
            height: width
            radius: width / 2
            color: "#929a9d"
        }
    }
    Image {
        anchors.fill: parent
        source: cover.artwork
        visible: status === Image.Ready
        fillMode: Image.PreserveAspectCrop
        asynchronous: false
    }
}
