import QtQuick
import "../Look.js" as Look

// An item's details, over the library or Search (Enter on a movie or a
// series): its poster, what it is, where you stopped, a series' episodes as
// TV-style rows, and Play or Resume. Styled by the box, menu and player
// elements.
Box {
  id: details

  required property var guide
  readonly property real u: guide.u

  readonly property var card: guide.libDetail
  readonly property bool series: !!card && card.kind === "series"
  readonly property var episode: series ? card.episodes[guide.libEpisode] : null
  readonly property string playId: !card ? "" : series ? (episode ? episode.id : "") : card.id
  readonly property real resume: playId ? guide.libResumeAt(playId) : 0

  function hms(t) {
    t = Math.max(0, Math.floor(t))
    var h = Math.floor(t / 3600)
    var m = Math.floor((t % 3600) / 60)
    var s = t % 60
    return (h ? h + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (s < 10 ? "0" : "") + s
  }

  visible: card !== null && !guide.watching && (guide.screen === "library" || guide.screen === "search")
  s: guide.look.scrim
  unit: u
  MouseArea { anchors.fill: parent; onClicked: guide.libDetail = null }

  Box {
    id: panel
    anchors.centerIn: parent
    width: Math.min(parent.width - details.u * 8, details.u * 80)
    height: Math.min(parent.height - details.u * 4, Math.max(poster.height, info.implicitHeight) + panel.padding * 2)
    s: guide.look.box
    unit: details.u
    image: guide.areaImages.box
    MouseArea { anchors.fill: parent }

    Image {
      id: poster
      x: panel.padding
      y: panel.padding
      width: details.u * 18
      height: implicitWidth > 0 ? Math.min(details.u * 28, width * implicitHeight / implicitWidth) : details.u * 10
      source: details.card ? guide.posterFor(details.card.entry || { poster: details.card.poster, videoId: details.card.videoId, live: details.card.live }) : ""
      fillMode: Image.PreserveAspectFit
      verticalAlignment: Image.AlignTop
      asynchronous: true
    }

    Column {
      id: info
      anchors.left: poster.right
      anchors.leftMargin: details.u * 2
      anchors.right: parent.right
      anchors.rightMargin: panel.padding
      y: panel.padding
      spacing: details.u * 0.9

      Label {
        width: parent.width
        text: details.card ? details.card.title : ""
        s: guide.look.boxTitle
        unit: details.u
        sizeFactor: 1.35
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
      }
      Label {
        width: parent.width
        visible: text !== ""
        text: !details.card ? "" : details.series ? details.card.sub : (details.card.entry || {}).subtitle || details.card.sub || ""
        s: guide.look.vodInfo
        unit: details.u
        sizeFactor: 1.15
      }
      Label {
        width: parent.width
        visible: text !== ""
        text: !details.card ? "" : details.series ? (details.episode ? details.episode.description : "") : (details.card.entry || {}).description || ""
        s: guide.look.boxText
        unit: details.u
        sizeFactor: 1.12
        wrapMode: Text.Wrap
        maximumLineCount: details.series ? 3 : 8
        elide: Text.ElideRight
      }
      Label {
        visible: details.resume > 0
        text: "You stopped at " + details.hms(details.resume)
        s: guide.look.vodTime
        unit: details.u
        sizeFactor: 1.15
      }

      // A series' episodes
      ListView {
        id: episodes
        visible: details.series
        readonly property real rowH: Math.round(Look.px(guide.look.menuRow.height, details.u * 0.8))
        width: parent.width
        height: visible ? Math.min(count, 5) * (rowH + spacing) : 0
        clip: true
        spacing: Math.round(details.u * 0.3)
        model: details.series ? details.card.episodes : []
        currentIndex: guide.libEpisode
        highlightRangeMode: ListView.ApplyRange
        preferredHighlightBegin: 0
        preferredHighlightEnd: height - rowH
        delegate: MenuRow {
          required property var modelData
          required property int index
          guide: details.guide
          width: episodes.width
          height: implicitHeight
          size: 0.8
          focused: index === guide.libEpisode
          label: "S" + modelData.season + " E" + modelData.episode + "   " + modelData.title
          value: guide.libFinished(modelData.id) ? "✓ Watched" : guide.libProgress(modelData.id) > 0.01 ? Math.round(guide.libProgress(modelData.id) * 100) + "%" : ""
          onActivated: {
            if (guide.libEpisode === index) guide.libPlay(false)
            else guide.libEpisode = index
          }
        }
      }

      KeyHints {
        model: [{ keys: ["ENTER"], label: details.resume > 0 ? "Resume" : "Play" }]
               .concat(details.resume > 0 ? [{ keys: ["R"], label: "Start over" }] : [])
               .concat(details.series ? [{ keys: ["↑", "↓"], label: "Episode" }] : [])
               .concat([{ keys: ["L"], label: details.playId && guide.inLibraryList(details.playId) ? "Take off My List" : "Add to My List" },
                        { keys: ["ESC"], label: "Back" }])
        size: details.u * 1.55
        capStyle: guide.look.keycap
        labelStyle: guide.look.keyLabel
      }
    }
  }
}
