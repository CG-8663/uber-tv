import QtQuick

// The card shown when changing channel: the channel's logo (or its initial
// in a frame), its number and name, and Tuning… or No signal, over a
// backdrop, styled by the card elements (Look.js). It fades in and out with `up`.
Item {
  id: ident

  property bool up: false
  property string logo: ""         // an image URL, or "" for the initial
  property string number: ""
  property string name: ""
  property string status: ""       // "tuning" (or "loading", on demand), "lost", or "" once the picture is on
  property real unit: 16           // sizes, from the space it's shown in
  property var look: ({})          // the guide's look, resolved
  property color alarm: "#ff4d4d"  // No signal
  property var image: null         // a picture over the backdrop ({ url, fit, opacity }), or null

  opacity: up ? 1 : 0
  visible: opacity > 0
  Behavior on opacity { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }

  Box {
    anchors.fill: parent
    s: ident.look.card || ({})
    unit: ident.unit
    image: ident.image
  }

  Column {
    anchors.centerIn: parent
    width: parent.width - ident.unit * 2
    spacing: ident.unit * 0.5

    Item {
      anchors.horizontalCenter: parent.horizontalCenter
      width: ident.unit * 7
      height: ident.unit * 5

      Box {
        anchors.centerIn: parent
        visible: picture.status !== Image.Ready
        width: ident.unit * 4.4
        height: width
        s: ident.look.cardFrame || ({})
        unit: ident.unit
        Label {
          anchors.centerIn: parent
          text: ident.name.charAt(0).toUpperCase()
          s: ident.look.cardFrame || ({})
          unit: ident.unit
        }
      }

      Image {
        id: picture
        anchors.fill: parent
        source: ident.logo
        sourceSize.width: 256
        sourceSize.height: 256
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        smooth: true
        opacity: status === Image.Ready ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 200 } }
      }
    }

    Label {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      text: (ident.number ? ident.number + "   " : "") + ident.name
      s: ident.look.cardName || ({})
      unit: ident.unit
      elide: Text.ElideRight
    }

    Label {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      visible: ident.status !== ""
      text: ident.status === "lost" ? "No signal" : ident.status === "loading" ? "Loading…" : "Tuning…"
      s: ident.look.cardStatus || ({})
      unit: ident.unit
      color: ident.status === "lost" ? ident.alarm : (s.text ? s.text.color : "#9fb0f0")
    }
  }
}
