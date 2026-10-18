"""Showcase: every block Uber TV draws, from packaged pictures and
made-up titles, so it runs offline (no network permission at all).

Try it:  python3 bin/om-pg-apps try apps/sdk/examples/showcase \\
           --call home --call 'details:{"item":"title:1"}' --call 'browse:{"item":"person:1"}'
"""

from uber_tv import app, Screen, Row, Item, Detail, Action, Message, AppError, Chart, Column, Page, Section

TITLES = [
    ("The Long Night", 2019, "2 h 10 min", "PG-13", ["Drama", "Mystery"]),
    ("Paper Moons", 2021, "1 h 48 min", "PG", ["Comedy"]),
    ("North of Nowhere", 2018, "2 h 2 min", "R", ["Thriller", "4K"]),
    ("Glass Harbor", 2022, "1 h 55 min", "PG-13", ["Drama"]),
    ("The Quiet Field", 2017, "1 h 39 min", "G", ["Family"]),
    ("Second Signal", 2023, "2 h 14 min", "PG-13", ["Sci-fi", "4K"]),
]


def pic(kind, n):
    """a packaged picture: poster-1.png, wide-2.png..."""
    count = {"poster": 3, "wide": 3, "backdrop": 3, "square": 4, "logo": 3, "person": 2}[kind]
    return "%s-%d.png" % (kind, (n - 1) % count + 1)


def title_item(n, kind="info", **extra):
    name, year, length, rating, _ = TITLES[(n - 1) % len(TITLES)]
    return Item("title:%d" % n, name, kind=kind, image=pic("poster", n),
                images={"poster": pic("poster", n), "wide": pic("wide", n), "backdrop": pic("backdrop", n), "logo": pic("logo", n)},
                meta="%d · %s · %s" % (year, length, rating), **extra)


@app.home
def home():
    featured = [title_item(n, text="A short line or two about this one: who, where and what happens, cut to fit.") for n in (1, 2, 3)]
    movies = [title_item(n, watched=(n == 2)) for n in range(1, 7)]
    resume = [Item("title:%d" % n, TITLES[n - 1][0], subtitle="S1 E%d" % n, kind="info", image=pic("wide", n),
                   images={"wide": pic("wide", n), "backdrop": pic("backdrop", n)}, progress=0.25 * n, badge="NEW" if n == 1 else "")
              for n in (1, 2, 3)]
    albums = [Item("album:%d" % n, "Album %d" % n, subtitle="Artist %d" % n, kind="info", image=pic("square", n)) for n in range(1, 5)]
    channels = [Item("channel:%d" % n, "Channel %d" % n, kind="info", images={"logo": pic("logo", n)}, badge="LIVE" if n == 1 else "") for n in range(1, 4)]
    # no shape given: the guide works it out from the first three pictures (wide, here)
    extras = [Item("extra:%d" % n, "Behind the scenes %d" % n, kind="info", image=pic("wide", n)) for n in range(1, 4)]
    people = [Item("person:%d" % n, "Person %d" % n, subtitle="Actor", kind="open", image=pic("person", n)) for n in range(1, 5)]
    library = [title_item(n, kind="info") for n in range(1, 9)]
    episodes = [Item("episode:%d" % n, "Episode %d" % n, subtitle="The Long Night", kind="info",
                     meta="S1 E%d · 52 min" % n, watched=n < 3) for n in range(1, 6)]
    # API 4: a ticker, a table (standings, with a chart of each one's form) and an article
    news = [Item("news:%d" % n, line, badge=badge) for n, (line, badge) in enumerate(
        [("Paper Moons tops the weekend", "NEW"), ("Glass Harbor gets a sequel", ""), ("Second Signal in 4K tonight", "4K")], 1)]
    standings = [Item("team:%d" % n, team, kind="info", cells=[str(n), team, str(w), str(l), "%.3f" % (w / (w + l))],
                      chart=Chart(form, low="0", high="10")) for n, (team, w, l, form) in enumerate(
        [("Harbor Gulls", 18, 6, [4, 6, 5, 8, 9]), ("North Owls", 15, 9, [7, 5, 6, 6, 7]), ("Moon Larks", 9, 15, [3, 4, 2, 5, 4])], 1)]
    reading = [Item("article:1", "How the Showcase was made", subtitle="An article page", kind="open")]
    return Screen("Showcase", rows=[
        Row("featured", "Featured", featured, layout="hero"),
        Row("movies", "Movies", movies, shape="poster"),
        Row("continue", "Continue watching", resume, shape="wide"),
        Row("albums", "Albums", albums, shape="square", size="small"),
        Row("channels", "Channels", channels, shape="logo"),
        Row("people", "People", people, shape="circle"),
        Row("extras", "Extras", extras),
        Row("library", "Library", library, layout="grid", shape="poster", size="small"),
        Row("episodes", "Episodes", episodes, layout="list"),
        Row("news", "News", news, layout="ticker"),
        Row("standings", "Standings", standings, layout="table",
            columns=[Column("#", "end"), Column("Team"), Column("W", "end"), Column("L", "end"), Column("Pct", "end")]),
        Row("reading", "Reading", reading, layout="list"),
    ], empty="Nothing to show.")


@app.browse
def browse(item):
    if item == "article:1":
        return Page("How the Showcase was made", sections=[
            Section("Pictures", "Every picture is a flat shape made for it: posters, wide stills, squares, logos and people.\nNo one's artwork."),
            Section("Blocks", "Each row shows another way Uber TV draws an app's screen: a featured row, cards of each shape, a grid, "
                              "a list, a table, a ticker, and this page, which the arrows scroll."),
            Section("Offline", "It asks for no network at all: try runs it without anything leaving the computer."),
        ])
    if item.startswith("person:"):
        n = int(item.split(":")[1])
        return Screen("Person %d" % n, rows=[Row("filmography", "Movies and shows", [title_item(m) for m in range(n, n + 4)], layout="grid", shape="poster")])
    raise AppError("There's nothing more here.")


@app.details
def details(item):
    kind, _, num = item.partition(":")
    n = int(num or 1)
    if kind == "team":
        return Detail("Team %d" % n, subtitle="Its last five games", style="classic", facts=[("Place", str(n))],
                      chart=Chart([4, 6, 5, 8, 9] if n == 1 else [7, 5, 6, 6, 7] if n == 2 else [3, 4, 2, 5, 4], low="0 points", high="10 points"))
    if kind != "title":
        return Detail(item.replace(":", " ").title(), subtitle="A details page in the classic style", image=pic("square" if kind == "album" else "logo", n),
                      facts=[("Kind", kind), ("Number", str(n))], style="classic")
    name, year, length, rating, chips = TITLES[(n - 1) % len(TITLES)]
    cast = [Item("person:%d" % p, "Person %d" % p, subtitle="Actor", kind="open", image=pic("person", p)) for p in (1, 2, 3)]
    more = [title_item(m) for m in range(n + 1, n + 5)]
    return Detail(name, subtitle="A made-up film", image=pic("poster", n), backdrop=pic("backdrop", n), logo=pic("logo", n),
                  style="cinematic" if n <= 3 else "classic", meta="%d · %s · %s" % (year, length, rating), chips=chips,
                  facts=[("Director", "Someone"), ("Runtime", length)],
                  text="An overview of it, in a few lines: who, where and what happens, cut to fit the page.",
                  actions=[Action("watched", "Mark watched"), Action("liked", "Like it")],
                  rows=[Row("cast", "Cast", cast, shape="circle"), Row("more", "More like this", more, shape="poster")])


@app.search
def search(query):
    q = query.lower().strip()
    hits = [title_item(n) for n in range(1, len(TITLES) + 1) if q and q in TITLES[n - 1][0].lower()]
    return Screen("Results for " + query, rows=[Row("results", "Titles", hits, shape="poster")] if hits else [], empty="Nothing matches " + query + ".")


@app.action
def action(item, act):
    return Message({"watched": "Marked as watched (an example: nothing is kept).", "liked": "Liked (an example: nothing is kept)."}.get(act, "Done."))


@app.home_row
def home_row(key):
    return [title_item(n) for n in (2, 4, 6)]


app.run()
