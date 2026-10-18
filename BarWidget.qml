import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import "Shortcut.js" as Shortcut

// The guide's TV in the Omarchy bar: click it to open or close the guide.
//
// For Omarchy this icon is also the guide's on switch: a third-party plugin is
// on while its entry is in the bar. To keep the guide but lose the icon, turn
// off "Show in the top bar" in the guide's Settings; the icon then takes no
// space. The setting and the shortcut are read from the guide's own
// settings.json (read only, never written here).
BarWidget {
  id: root
  moduleName: "marcho78.om-pg"

  property bool wanted: true
  property string shortcut: Shortcut.DEFAULT

  visible: wanted
  implicitWidth: wanted ? button.implicitWidth : 0
  implicitHeight: wanted ? button.implicitHeight : 0

  FileView {
    path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/om-pg/settings.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      var raw = text()
      if (raw.length > 4 * 1024 * 1024) return
      try {
        var saved = JSON.parse(raw)
        root.wanted = !saved.bar || saved.bar.icon !== false
        root.shortcut = saved.bar && typeof saved.bar.shortcut === "string" ? saved.bar.shortcut : Shortcut.DEFAULT
      } catch (e) {}
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // Material Design "television"
    text: String.fromCodePoint(0xf0502)
    tooltipText: "Uber TV" + (Shortcut.label(root.shortcut) ? " · " + Shortcut.label(root.shortcut) : "")
    onPressed: function(mouseButton) {
      if (root.bar && root.bar.shell && typeof root.bar.shell.toggle === "function")
        root.bar.shell.toggle("marcho78.om-pg", "{}")
    }
  }
}
