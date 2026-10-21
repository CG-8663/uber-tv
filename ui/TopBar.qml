import QtQuick

// The masthead as a thin status line (layout.masthead bar): a badge, the
// guide's name, what's shown and from where, and on the right what's
// recording, how old the listings are and the clock. While the AI agent skill is off and you
// haven't said yes or no, it says so here too.
Box {
  id: bar

  required property var guide

  readonly property real labelSize: guide.look.barLabel.text.size || 0.85
  readonly property string filterText: guide.managing ? "managing" + (guide.markedCount ? " · " + guide.markedCount + " marked" : "")
                                     : guide.shownCategories.length ? guide.shownCategories.filter(function(c) { return guide.categories.indexOf(c) >= 0 })
                                                                                           .map(guide.categoryName).join(", ")
                                     : "all"
  readonly property string listingsAge: {
    if (!guide.fetchedAt) return "not yet"
    var mins = Math.max(0, Math.round((guide.now - guide.fetchedAt) / 60))
    return mins < 1 ? "just now" : mins < 60 ? mins + "m ago" : Math.round(mins / 60) + "h ago"
  }

  height: Math.max(guide.u * 1.8, row.implicitHeight + bar.padding * 2)
  s: guide.look.topBar
  unit: guide.u

  Row {
    id: row
    anchors.left: parent.left
    anchors.leftMargin: bar.padding
    anchors.verticalCenter: parent.verticalCenter
    spacing: guide.u * 0.8

    Box {
      id: badge
      anchors.verticalCenter: parent.verticalCenter
      width: badgeText.implicitWidth + badge.padding * 2
      height: badgeText.implicitHeight + badge.padding
      s: guide.look.barBadge
      unit: guide.u
      Label {
        id: badgeText
        anchors.centerIn: parent
        text: "om-pg"
        s: guide.look.barBadge
        unit: guide.u
      }
    }
    Label {
      anchors.verticalCenter: parent.verticalCenter
      text: "Uber TV"
      s: guide.look.title
      unit: guide.u
      sizeFactor: bar.labelSize / Math.max(0.2, guide.look.title.text.size)
    }
    Label { anchors.verticalCenter: parent.verticalCenter; text: "│"; s: guide.look.barLabel; unit: guide.u }
    Row {
      anchors.verticalCenter: parent.verticalCenter
      spacing: guide.u * 0.4
      Label { text: "filter"; s: guide.look.barLabel; unit: guide.u }
      Label { text: bar.filterText; s: guide.look.barValue; unit: guide.u; width: Math.min(implicitWidth, bar.width * 0.25); elide: Text.ElideRight }
    }
    Row {
      anchors.verticalCenter: parent.verticalCenter
      visible: guide.hasIptv
      spacing: guide.u * 0.4
      Label { text: "sources"; s: guide.look.barLabel; unit: guide.u }
      Label { text: guide.hasIptv && guide.shownSource !== "both" ? guide.sourceName(guide.shownSource) : "YouTube + IPTV"; s: guide.look.barValue; unit: guide.u }
    }
  }

  Row {
    anchors.right: parent.right
    anchors.rightMargin: bar.padding
    anchors.verticalCenter: parent.verticalCenter
    spacing: guide.u * 0.8

    Row {
      anchors.verticalCenter: parent.verticalCenter
      visible: guide.agentStripUp
      spacing: guide.u * 0.4
      Label { text: "AI agents can theme the guide:"; s: guide.look.barLabel; unit: guide.u }
      Label { text: ", settings"; s: guide.look.barValue; unit: guide.u }
      Label { text: "│"; s: guide.look.barLabel; unit: guide.u }
    }
    // what's recording (● Recording CBS News, ● 2 recording)
    Label {
      anchors.verticalCenter: parent.verticalCenter
      visible: guide.recordingNow !== ""
      text: guide.recordingNow
      s: guide.look.mastheadRec
      unit: guide.u
      sizeFactor: bar.labelSize / Math.max(0.2, guide.look.mastheadRec.text.size)
    }
    Row {
      anchors.verticalCenter: parent.verticalCenter
      spacing: guide.u * 0.4
      Label { text: "listings"; s: guide.look.barLabel; unit: guide.u }
      Label { text: bar.listingsAge; s: guide.look.barLabel; unit: guide.u }
    }
    Label {
      anchors.verticalCenter: parent.verticalCenter
      visible: guide.layout.clock === "masthead"
      text: "│"
      s: guide.look.barLabel
      unit: guide.u
    }
    Label {
      anchors.verticalCenter: parent.verticalCenter
      visible: guide.layout.clock === "masthead"
      text: Qt.formatDateTime(new Date(guide.now * 1000), "ddd d MMM") + " " + guide.clock(guide.now)
      s: guide.look.barValue
      unit: guide.u
    }
  }
}
