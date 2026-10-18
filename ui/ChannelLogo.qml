import QtQuick

// A channel's logo with logos on (L), or its initial until there is one, in
// the logo badge's box; a locked channel gets a lock, never its logo. The
// table and the board put it before the channel's name (the grid has its own,
// shown in a row with logos off too).
Box {
  id: badge

  required property var guide
  property var channel: ({ name: "", kind: "" })
  property bool locked: false

  s: guide.look.logoBadge
  unit: guide.u

  Label {
    anchors.centerIn: parent
    visible: logo.status !== Image.Ready && !badge.locked
    text: String(badge.channel.name || "").charAt(0).toUpperCase()
    s: badge.guide.look.logoBadge
    unit: badge.guide.u
    // the badge's letter, shrunk to fit a box smaller than the grid's
    sizeFactor: Math.min(1, badge.height * 0.6 / Math.max(1, (s.text ? s.text.size : 1) * unit))
  }
  Icon {
    anchors.centerIn: parent
    visible: badge.locked
    name: "lock"
    size: parent.height * 0.62
    stroke: 1.8
    color: badge.guide.look.logoBadge.text.color
  }
  Image {
    id: logo
    anchors.fill: parent
    anchors.margins: Math.max(1, badge.borderWidth)
    source: badge.guide.showLogos && !badge.locked ? badge.guide.logoSource(badge.channel) : ""
    sourceSize.width: 96
    sourceSize.height: 96
    // YouTube avatars are square; IPTV logos are often wide.
    fillMode: badge.channel.kind === "iptv" ? Image.PreserveAspectFit : Image.PreserveAspectCrop
    asynchronous: true
    smooth: true
  }
}
