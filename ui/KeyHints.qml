import QtQuick

// A row of hints: keycaps, then what they do. Each hint is
// { keys: ["SHIFT", "+", "SPACE"], label: "Mark category" }; "+" (together)
// and "/" (either) are drawn as plain text between keys. The keycap and key
// label elements (Look.js) style them; labelColor, where given, colors the
// labels instead (the managing footer, say).
Row {
  id: hints

  property var model: []
  property real size: 24
  property var capStyle: ({})
  property var labelStyle: ({})
  property var labelColor: undefined

  readonly property color textColor: labelColor !== undefined ? labelColor : (labelStyle.text ? labelStyle.text.color : "#9fb0f0")

  spacing: size * 0.9

  Repeater {
    model: hints.model
    delegate: Row {
      id: hint
      required property var modelData
      spacing: hints.size * 0.25

      Repeater {
        model: modelData.keys
        delegate: Loader {
          required property string modelData
          anchors.verticalCenter: parent.verticalCenter
          // "+" and "/" between keys join them; on its own, "/" is the slash key
          sourceComponent: (modelData === "+" || modelData === "/") && hint.modelData.keys.length > 1 ? joiner : keycap
          property string key: modelData
        }
      }

      Label {
        anchors.verticalCenter: parent.verticalCenter
        leftPadding: modelData.keys.length ? hints.size * 0.15 : 0
        text: modelData.label
        s: hints.labelStyle
        unit: hints.size
        color: hints.textColor
      }
    }
  }

  Component {
    id: keycap
    Keycap {
      label: parent ? parent.key : ""
      size: hints.size
      s: hints.capStyle
    }
  }

  Component {
    id: joiner
    Label {
      text: parent ? parent.key : ""
      s: hints.labelStyle
      unit: hints.size
      sizeFactor: 0.55 / 0.58
      color: hints.textColor
    }
  }
}
