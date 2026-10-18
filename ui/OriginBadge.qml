import QtQuick
import "../AppLooks.js" as Looks
import "../Look.js" as Look

// Where an app is from, as a small icon instead of words:
// on its tile on the Apps screen, on Home (its card, and beside its own
// rows' names) and on its band. Uber TV's own apps
// (bundled, the catalog) get none; a signed app file or an unsigned Developer
// mode file gets a page. An opaque rounded square of its own with an edge,
// drawn over the app's picture: whatever the theme's color (appOrigin), it's
// made solid, so nothing in the picture shows through, and never smaller
// than a floor; its icon is black or white, whichever reads better on it
// (at least 4.5:1 against any solid fill). The app has no say in any of it.
Rectangle {
  id: badge

  required property var guide
  property string from: ""              // an app's from: "appFile" or "file" (anything else: hidden)
  property real u: guide.u
  readonly property var part: guide.look && guide.look.appOrigin ? guide.look.appOrigin : ({})
  readonly property color fill: badge.solid(part.color || guide.colors.boxBg)
  readonly property color ink: Looks.contrast("#ffffff", String(fill)) >= Looks.contrast("#000000", String(fill)) ? "#ffffff" : "#000000"

  function solid(c) { var q = Qt.color(String(c)); return Qt.rgba(q.r, q.g, q.b, 1) }

  objectName: "originBadge"
  visible: from === "appFile" || from === "file"
  width: Math.max(Math.round(u * 1.4), Math.round(Look.px(part.size === undefined ? 1.7 : part.size, u)))
  height: width
  radius: width * 0.25
  color: fill
  opacity: 1
  border.width: Math.max(1, Math.round(width * 0.06))
  border.color: badge.solid(part.edge || guide.colors.boxBorder)

  Icon {
    anchors.centerIn: parent
    name: "file"
    size: badge.width * 0.68
    stroke: 2
    color: badge.ink
  }
}
