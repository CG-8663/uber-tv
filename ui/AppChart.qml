import QtQuick
import QtQuick.Shapes
import "../Look.js" as Look

// A chart an app sent (api 4, lib/appblocks.py chart): its points, oldest
// first, as one line, drawn by the guide in the look's chart color (the
// app styles nothing); what its top and bottom mean, if it said, small at
// its left. In a list or table line, and on a details page.
Item {
  id: chart

  required property var guide
  property var data: null            // { points, low, high }
  property real u: guide.u
  property bool labels: true
  property var labelStyle: guide.look.appTableHead
  readonly property var pts: data && Array.isArray(data.points) ? data.points : []
  readonly property real lo: pts.length ? Math.min.apply(null, pts) : 0
  readonly property real hi: pts.length ? Math.max.apply(null, pts) : 1
  readonly property bool said: labels && !!data && (!!data.low || !!data.high)
  readonly property real labelW: said ? Math.min(width * 0.4, Math.max(lowLabel.implicitWidth, highLabel.implicitWidth) + u * 0.6) : 0
  readonly property real stroke: Math.max(1, Math.round(Look.px(guide.look.appChart ? guide.look.appChart.width : 0.15, u)))
  // the points across its width, the lowest at its bottom and the highest at
  // its top (a flat line across its middle); scaled first when the span
  // itself overflows (two finite ends near the largest numbers), so every
  // coordinate stays a finite number
  readonly property var coords: {
    var n = chart.pts.length, w = line.width, h = line.height, m = chart.stroke
    if (n < 2 || w <= 0 || h <= 0) return []
    var k = isFinite(chart.hi - chart.lo) ? 1 : Math.max(Math.abs(chart.lo), Math.abs(chart.hi))
    var lo = chart.lo / k, span = chart.hi / k - lo
    return chart.pts.map(function(p, i) {
      var f = span > 0 ? (p / k - lo) / span : 0.5
      var y = isFinite(f) ? m + (1 - f) * (h - 2 * m) : h / 2
      return Qt.point(m + i * (w - 2 * m) / (n - 1), y)
    })
  }

  visible: pts.length >= 2

  Label {
    id: highLabel
    visible: chart.said
    width: chart.labelW
    text: chart.data && chart.data.high ? chart.data.high : ""
    s: chart.labelStyle
    unit: chart.u
    sizeFactor: 0.8
    elide: Text.ElideRight
  }
  Label {
    id: lowLabel
    visible: chart.said
    y: chart.height - height
    width: chart.labelW
    text: chart.data && chart.data.low ? chart.data.low : ""
    s: chart.labelStyle
    unit: chart.u
    sizeFactor: 0.8
    elide: Text.ElideRight
  }
  Shape {
    id: line
    x: chart.labelW
    width: chart.width - chart.labelW
    height: chart.height
    preferredRendererType: Shape.CurveRenderer
    ShapePath {
      strokeColor: chart.guide.look.appChart && chart.guide.look.appChart.color ? chart.guide.look.appChart.color : chart.guide.marquee
      strokeWidth: chart.stroke
      fillColor: "transparent"
      joinStyle: ShapePath.RoundJoin
      capStyle: ShapePath.RoundCap
      PathPolyline { path: chart.coords }
    }
  }
}
