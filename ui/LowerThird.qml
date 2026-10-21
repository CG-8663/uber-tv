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
// by the arrows, and a click picks one (optionPicked). A recording's choices
// (rec) are drawn as the record choice element, with their note under them
// (what to know before Record is pressed), dimmed when they can't start
// (unavailable); recording, when given, is the REC badge over the clock.
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
  property var options: []         // [{ label, icon, rec, note, unavailable }], or none
  property string recording: ""    // "● REC until 9:00", or none
  property string timeshift: ""    // pause and rewind: "Live", "2:15 behind live", or none
  property bool behindLive: false
  property string note: ""         // a word above the banner while its choices aren't up (two streams from one provider)
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
      spacing: lt.recording || lt.timeshift ? lt.unit * 0.3 : 0
      Box {
        id: tsChip
        anchors.right: parent.right
        visible: lt.timeshift !== ""
        readonly property var st: lt.behindLive ? (lt.look["liveChip:behind"] || lt.look.liveChip || ({})) : (lt.look.liveChip || ({}))
        width: visible ? tsText.implicitWidth + tsChip.padding * 2 : 0
        height: visible ? tsText.implicitHeight + tsChip.padding * 0.6 : 0
        s: tsChip.st
        unit: lt.unit
        Label {
          id: tsText
          anchors.centerIn: parent
          text: lt.timeshift
          s: tsChip.st
          unit: lt.unit
        }
      }
      Box {
        id: recBadge
        anchors.right: parent.right
        visible: lt.recording !== ""
        width: visible ? recText.implicitWidth + recBadge.padding * 2 : 0
        height: visible ? recText.implicitHeight + recBadge.padding * 0.6 : 0
        s: lt.look.recordBadge || ({})
        unit: lt.unit
        Label {
          id: recText
          anchors.centerIn: parent
          text: lt.recording
          s: lt.look.recordBadge || ({})
          unit: lt.unit
        }
      }
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

  // A word above the banner (the choices take its place)
  Box {
    id: noteBox
    visible: lt.note !== "" && lt.options.length === 0
    x: banner.x
    y: banner.y - height - lt.unit * 0.8
    width: noteText.implicitWidth + lt.unit * 1.6
    height: noteText.implicitHeight + lt.unit * 0.8
    s: lt.look.recordWarning || ({})
    unit: lt.unit
    Label { id: noteText; anchors.centerIn: parent; text: lt.note; s: lt.look.recordWarning || ({}); unit: lt.unit }
  }

  // The choices, just above the banner
  readonly property bool anyNote: options.some(function(o) { return !!o.note })
  readonly property real noteMax: lt.unit * 24     // a note wider wraps: no choice runs off the screen
  Row {
    id: choices
    visible: lt.options.length > 0
    x: banner.x
    y: banner.y - height - lt.unit * 0.8
    // as tall as the tallest choice (a note on two lines), all the same
    readonly property real tallest: {
      var h = 0
      for (var i = 0; i < choiceList.count; i++) { var it = choiceList.itemAt(i); if (it) h = Math.max(h, it.inside) }
      return h
    }
    height: Math.max(lt.unit * (lt.anyNote ? 4 : 2.8), tallest + lt.unit * 1.2)
    spacing: lt.unit * 0.6
    Repeater {
      id: choiceList
      model: lt.options
      Box {
        id: option
        required property var modelData
        required property int index
        readonly property string el: option.modelData.rec ? "recordChoice" : "menuRow"
        readonly property var st: index === lt.optionFocus ? (lt.look[el + ":focused"] || ({})) : (lt.look[el] || ({}))
        readonly property real inside: optionCol.implicitHeight
        width: Math.max(optionRow.implicitWidth, noteLabel.visible ? noteLabel.width : 0) + lt.unit * 2.2
        height: parent.height
        s: st
        unit: lt.unit * 0.8
        opacity: option.modelData.unavailable ? 0.55 : 1
        Column {
          id: optionCol
          anchors.centerIn: parent
          spacing: lt.unit * 0.15
          Row {
            id: optionRow
            anchors.horizontalCenter: parent.horizontalCenter
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
          Label {
            id: noteLabel
            readonly property bool picked: option.index === lt.optionFocus
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(implicitWidth, lt.noteMax)
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            visible: !!option.modelData.note
            text: option.modelData.note || ""
            s: lt.look.recordNote || ({})
            unit: lt.unit * 0.8
            // on the picked choice, in that choice's own text color, a little
            // dimmer: the note's color is for the others, and reads poorly on a picked one's fill
            color: picked && option.st.text && option.st.text.color ? option.st.text.color : (t.color || "white")
            opacity: picked ? 0.8 : 1
          }
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: lt.optionPicked(option.index) }
      }
    }
  }
}
