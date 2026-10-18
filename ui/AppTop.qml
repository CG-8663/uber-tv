import QtQuick
import "../Look.js" as Look
import "../AppLooks.js" as Looks
import "../AppNav.js" as Nav

// The top of an app's screen when it shows what's selected (§4.4), like the
// top of Home: the row's name, the title, its line, how far in, and two
// lines of its text. Hidden while nothing is selected. Plain text. The
// title keeps its floor (1.4 units) and is drawn fully opaque in a color
// that reads against what's behind it, on a plate where nothing does.
Item {
  id: top

  required property var guide
  required property var view
  required property var host           // the app screen it's on

  readonly property real u: guide.u
  readonly property var at: host.model && host.model.lines.length ? Nav.current(host.model, view.sel) : null
  readonly property var thing: at && at.line.kind === "row" ? at.thing : null
  readonly property var titleStyle: Looks.floored(guide.look.appTopTitle, Looks.TOP_TITLE, u, 1)
  readonly property var title: Looks.titleColor(String(titleStyle.text ? titleStyle.text.color : ""), String(guide.ink), host.pageColor, host.around)
  readonly property var bar: guide.look.appProgress

  objectName: "appTop"
  visible: !!thing

  Column {
    x: top.u * 3
    width: Math.min(top.width - top.u * 6, top.u * 62)
    spacing: top.u * 0.4
    Label {
      objectName: "topKicker"
      width: parent.width
      text: top.at ? top.at.line.title || "" : ""
      s: top.guide.look.appTopKicker
      unit: top.u
      elide: Text.ElideRight
    }
    Item {
      width: parent.width
      height: topTitle.implicitHeight
      // where nothing else reads, a backing plate
      Rectangle {
        visible: top.title.plate !== ""
        x: -top.u * 0.3
        y: -top.u * 0.1
        width: Math.min(parent.width, topTitle.implicitWidth) + top.u * 0.6
        height: topTitle.implicitHeight + top.u * 0.2
        radius: top.u * 0.25
        color: top.title.plate || "transparent"
      }
      Label {
        id: topTitle
        objectName: "topTitle"
        width: parent.width
        text: top.thing ? top.thing.title : ""
        s: top.titleStyle
        unit: top.u
        color: top.title.color
        opacity: 1
        elide: Text.ElideRight
        maximumLineCount: 1
      }
    }
    Label {
      objectName: "topMeta"
      width: parent.width
      visible: text !== ""
      text: top.thing ? (top.thing.meta || top.thing.subtitle || "") : ""
      s: top.guide.look.appTopMeta
      unit: top.u
      elide: Text.ElideRight
      maximumLineCount: 1
    }
    Rectangle {
      visible: !!top.thing && top.thing.progress !== null && top.thing.progress > 0.01
      width: top.u * 22
      height: Math.max(3, Look.px(top.bar.height, top.u))
      radius: height / 2
      color: top.bar.track || "transparent"
      Rectangle {
        height: parent.height
        radius: parent.radius
        width: parent.width * (top.thing && top.thing.progress ? top.thing.progress : 0)
        color: top.bar.fill && typeof top.bar.fill === "object" ? top.bar.fill.from : (top.bar.fill || "transparent")
      }
    }
    Label {
      objectName: "topText"
      width: parent.width
      visible: text !== ""
      text: top.thing ? (top.thing.text || "") : ""
      s: top.guide.look.appTopText
      unit: top.u
      wrapMode: Text.Wrap
      maximumLineCount: 2
      elide: Text.ElideRight
    }
  }
}
