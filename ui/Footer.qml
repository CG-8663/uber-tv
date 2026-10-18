import QtQuick

// The key hints along the bottom: the essentials (? lists every key). As a
// status line (layout.footer status) they come after a mode badge, with the
// channel count on the right.
Box {
  id: footer

  required property var guide

  readonly property bool status: guide.layout.footer === "status"

  visible: guide.showKeyHints || guide.managing
  height: visible ? guide.u * (status ? 1.7 : 1.9) : 0
  s: guide.look.footer
  unit: guide.u

  // GUIDE, MANAGE…
  Box {
    id: mode
    visible: footer.status
    anchors.left: parent.left
    anchors.leftMargin: footer.padding
    anchors.verticalCenter: parent.verticalCenter
    width: visible ? modeText.implicitWidth + mode.padding * 2 : 0
    height: modeText.implicitHeight + mode.padding
    s: guide.look.modeBadge
    unit: guide.u
    Label {
      id: modeText
      anchors.centerIn: parent
      text: guide.managing ? "Manage" : guide.dialog === "style" ? "Style" : guide.dialog !== "" ? "Box" : "Guide"
      s: guide.look.modeBadge
      unit: guide.u
    }
  }

  // The essentials; ? lists every key. Shrinks to fit narrow screens.
  KeyHints {
    id: hints
    anchors.left: mode.right
    anchors.leftMargin: footer.status ? guide.u * 0.8 : footer.padding
    anchors.verticalCenter: parent.verticalCenter
    transformOrigin: Item.Left
    scale: Math.min(1, ((footer.status ? counts.x - guide.u : footer.width) - x) / Math.max(1, implicitWidth))
    model: guide.footerHints
    size: guide.u * (footer.status ? 1.3 : 1.55)
    capStyle: guide.look.keycap
    labelStyle: guide.look.keyLabel
    labelColor: guide.managing ? guide.marquee : undefined
  }

  Label {
    id: counts
    visible: footer.status
    anchors.right: parent.right
    anchors.rightMargin: footer.padding + guide.u * 0.4
    anchors.verticalCenter: parent.verticalCenter
    text: guide.visibleRows.length + " ch · " + guide.categories.filter(function(c) { return guide.categoryCounts[c] }).length + " categories"
    s: guide.look.barLabel
    unit: guide.u
  }
}
