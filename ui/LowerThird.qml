import QtQuick
import "../Look.js" as Look

// The channel banner across the bottom of the TV: logo, number, channel
// name, what's on with how far in it is, the clock and the show's times.
// It fills the space it's given and places the banner in it by the lower
// third element (Look.js): its height, its margin from the edges, its width
// (full, or a share) and which side it keeps to. The lt* elements style
// what's on it; image is its picture, if any. options, when given, are a
// row of choices just above it (I or Space while watching: Multiview, Mini
// player, Guide…), drawn as the menu rows are; optionFocus is the one picked
// by the arrows, and a click picks one (optionPicked).
Item {
  id: lt

  property var look: ({})          // the guide's look, resolved
  property real unit: 16
  property string logo: ""
  property string number: ""
  property string channel: ""
  property string title: ""
  property real progress: -1       // 0–1, or below 0 for none (live)
  property string clock: ""
  property string times: ""
  property var image: null         // a picture over the background ({ url, fit, opacity }), or null
  property var options: []         // [{ label, icon }], or none
  property int optionFocus: -1
  signal optionPicked(int index)

  readonly property var s: look.lowerThird || ({})
  readonly property real margin: Look.px(s.margin !== undefined ? s.margin : 2, unit)
  readonly property var bar: look.ltProgress || ({})

  Box {
    id: banner
    s: lt.s
    unit: lt.unit
    image: lt.image
    height: Look.px(lt.s.height !== undefined ? lt.s.height : 7, lt.unit)
    width: typeof lt.s.width === "number" ? Math.max(lt.unit * 12, (lt.width - lt.margin * 2) * lt.s.width) : lt.width - lt.margin * 2
    x: lt.s.align === "left" ? lt.margin : lt.s.align === "right" ? lt.width - lt.margin - width : (lt.width - width) / 2
    y: lt.height - lt.margin - height

    Image {
      id: logoImage
      anchors.left: parent.left
      anchors.leftMargin: banner.padding
      anchors.verticalCenter: parent.verticalCenter
      width: status === Image.Ready ? lt.unit * 5 : 0
      height: lt.unit * 4.6
      source: lt.logo
      sourceSize.width: 256
      sourceSize.height: 256
      fillMode: Image.PreserveAspectFit
      asynchronous: true
    }

    Label {
      id: numberText
      anchors.left: logoImage.right
      anchors.leftMargin: lt.unit * 1.2
      anchors.verticalCenter: parent.verticalCenter
      text: lt.number
      s: lt.look.ltNumber || ({})
      unit: lt.unit
    }

    Column {
      anchors.left: numberText.right
      anchors.leftMargin: lt.unit * 1.2
      anchors.right: clockColumn.left
      anchors.rightMargin: lt.unit
      anchors.verticalCenter: parent.verticalCenter
      spacing: lt.unit * 0.3

      Label {
        width: parent.width
        text: lt.channel
        s: lt.look.ltChannel || ({})
        unit: lt.unit
        elide: Text.ElideRight
      }
      Label {
        width: parent.width
        text: lt.title
        s: lt.look.ltTitle || ({})
        unit: lt.unit
        elide: Text.ElideRight
      }
      Rectangle {
        width: parent.width
        height: Look.px(lt.bar.height !== undefined ? lt.bar.height : 0.5, lt.unit)
        radius: Math.min(height / 2, Look.px(lt.bar.radius, lt.unit))
        color: lt.bar.track || "transparent"
        Rectangle {
          height: parent.height
          width: lt.progress < 0 ? 0 : parent.width * Math.min(1, lt.progress)
          radius: parent.radius
          color: lt.bar.fill && typeof lt.bar.fill === "object" ? lt.bar.fill.from : (lt.bar.fill || "transparent")
        }
      }
    }

    Column {
      id: clockColumn
      anchors.right: parent.right
      anchors.rightMargin: banner.padding
      anchors.verticalCenter: parent.verticalCenter
      Label {
        anchors.right: parent.right
        text: lt.clock
        s: lt.look.ltClock || ({})
        unit: lt.unit
      }
      Label {
        anchors.right: parent.right
        text: lt.times
        s: lt.look.ltTime || ({})
        unit: lt.unit
      }
    }
  }

  // The choices, just above the banner
  Row {
    visible: lt.options.length > 0
    x: banner.x
    y: banner.y - height - lt.unit * 0.8
    height: lt.unit * 2.8
    spacing: lt.unit * 0.6
    Repeater {
      model: lt.options
      Box {
        id: option
        required property var modelData
        required property int index
        readonly property var st: index === lt.optionFocus ? (lt.look["menuRow:focused"] || ({})) : (lt.look.menuRow || ({}))
        width: optionRow.implicitWidth + lt.unit * 2.2
        height: lt.unit * 2.8
        s: st
        unit: lt.unit * 0.8
        Row {
          id: optionRow
          anchors.centerIn: parent
          spacing: lt.unit * 0.5
          Icon {
            visible: !!option.modelData.icon
            anchors.verticalCenter: parent.verticalCenter
            name: option.modelData.icon || ""
            size: lt.unit * 1.2
            stroke: 1.8
            color: option.st.text && option.st.text.color ? option.st.text.color : "white"
          }
          Label { anchors.verticalCenter: parent.verticalCenter; text: option.modelData.label; s: option.st; unit: lt.unit * 0.8 }
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: lt.optionPicked(option.index) }
      }
    }
  }
}
