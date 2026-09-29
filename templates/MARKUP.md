# Markup reference

The mockups have been removed; `build.py` + `templates/base.html` now generate this markup (see `dist/`). All text from
content files is HTML-escaped except news text and bio paragraphs. Links to other pages and static files are
relative (`research.html`, `static/files/cv.pdf`); content-file paths such as `files/cv.pdf` are prefixed with `static/` at build time.

## Shell (identical on every page; `base.html`)

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>$title</title>            <!-- home: "Daniel Pearson"; others: "Publications · Daniel Pearson" -->
  <meta name="description" content="$description">
  <link rel="preload" href="static/fonts/0xpropo-latin-500.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="static/fonts/0xproto-latin-700.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="static/css/style.css">
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <a class="site-name" href="index.html">Daniel Pearson</a>      <!-- site.toml name -->
    <nav class="site-nav" aria-label="Main">
      <ul>
        <li><a href="research.html">Research</a></li>              <!-- one per site.toml nav item -->
        <li><a href="news.html" aria-current="page">News</a></li>  <!-- aria-current only on active page -->
      </ul>
    </nav>
  </header>
  <main id="main">
$content
  </main>
  <footer class="site-footer">
    <p>&copy; 2026 Daniel Pearson</p>                              <!-- build year, name -->
    <p>Last built <time datetime="2026-09-29">29 September 2026</time></p>
  </footer>
</body>
</html>
```

The home page has no "active" nav item. Every page except home starts `<main>` with `<h1 class="page-title">`.

## Group (the one layout pattern: label in left column, content right)

Used for year groups (publications, talks, news), sections (News on home, teaching roles, Lab members, Collaborators)
and news. Labels are shown as written (no CSS case change); fixed labels are written lowercase.

```html
<section class="group">
  <h2 class="group-label">2017</h2>
  <div class="group-body">
    <ul class="entries"> <li class="entry">...</li> ... </ul>
  </div>
</section>
```

Years newest first; entries within a year in source order. `ul.entries` gets extra class `entries--compact`
(`class="entries entries--compact"`) for people lists and teaching courses.

## Entry variants (all `li.entry` inside `ul.entries`)

Publication (title, authors, venue; links optional). Authors formatted "Surname, I., ... , &amp; Surname, I.";
owner as `<strong>Pearson, D.</strong>` (two authors: "A &amp; B", no comma). Venue: `<em>Journal</em>, vol(issue), pages.` (en dash in pages).
Link labels: `PDF`, `DOI` (plain text; only emit those that exist).

```html
<li class="entry">
  <p class="entry-title">Title</p>
  <p class="entry-authors">Beesley, T., <strong>Pearson, D.</strong>, &amp; Le Pelley, M.</p>
  <p class="entry-venue"><em>Journal</em>, 22(3), 800&ndash;807. <span class="entry-links"><a href="static/files/x.pdf">PDF</a> <a href="https://doi.org/...">DOI</a></span></p>
</li>
```

Talk (no authors line). `howpublished, location.`; optional poster link labelled `Poster`.

```html
<li class="entry">
  <p class="entry-title">Talk title</p>
  <p class="entry-venue">Event name, Location. <span class="entry-links"><a href="static/files/poster.pdf">Poster</a></span></p>
</li>
```

News (dated entry; `datetime` is the ISO date, visible text "Sep 2026"; text is inline HTML). Home shows the
latest 3 in one `group` labelled "News" followed by `<p class="more"><a href="news.html">All news</a></p>`
placed inside `.group-body` after the `ul`. news.html groups by year like publications.

```html
<li class="entry">
  <time class="entry-meta" datetime="2026-09-29">Sep 2026</time>
  <p class="entry-text">Text, <a href="#">inline HTML allowed</a>.</p>
</li>
```

Person / collaborator (inside a `group` with `entries entries--compact`). Name may be wrapped in `<a>` if url.
Lab member detail: role, then ". note" if present. Collaborator detail: institution.

```html
<li class="entry">
  <p class="entry-title">Name</p>
  <p class="entry-detail">Role. Optional note.</p>
</li>
```

Research project (no year label; all projects sit in one `div.projects`, which is placed in the content column on
desktop; `description` is inline HTML). Collaborators line and "Key papers" list only if present. Each paper is
"Surname et al. (Year). Title." (one author: "Surname", two: "A &amp; B") with the title linked to the DOI, else the local PDF.

```html
<div class="projects">
  <article class="project">
    <h2 class="project-title">Project title</h2>
    <p class="project-text">Description.</p>
    <p class="entry-detail">With A, B</p>
    <p class="project-papers-label">Key papers</p>
    <ul class="entries entries--compact">
      <li class="entry"><p class="entry-detail">Pearson et al. (2016). <a href="https://doi.org/...">Paper title</a>.</p></li>
    </ul>
  </article>
</div>
```

Teaching (`teaching.html`: one `group` per role, labelled with the role title, whose body is a compact list of courses).
A role with a `section` key is preceded by `<h2 class="section-title">Past appointments</h2>` (in the content column
on desktop), and every group label after it becomes `h3`.

```html
<section class="group">
  <h2 class="group-label">Role title</h2>
  <div class="group-body">
    <ul class="entries entries--compact">
      <li class="entry entry-row">
        <span class="entry-code">PSYC1001</span>
        <span class="entry-name">Course name</span>
        <span class="entry-years">2023&ndash;present</span>
      </li>
    </ul>
  </div>
</section>
```

## Home intro (index.html only, before the News group)

```html
<section class="intro">
  <img class="portrait" src="static/img/portrait.jpg" alt="Portrait of Daniel Pearson" width="400" height="500">
  <div class="intro-text">
    <h1 class="name">Daniel Pearson</h1>
    <p class="position">Position, Department, University</p>
    <div class="prose"><p>Bio paragraph (inline HTML)</p><p>...</p></div>
    <nav class="contact" aria-label="Contact">
      <ul>
        <li><a href="mailto:...">Email</a></li>
        <li><a href="https://profiles.sydney.edu.au/daniel.pearson">University profile</a></li>
        <li><a href="https://scholar.google.com.au/citations?user=CxlKCBUAAAAJ">Google Scholar</a></li>
        <li><a href="https://orcid.org/0000-0003-1903-4019">ORCID</a></li>
      </ul>
    </nav>
  </div>
</section>
```

Notes: the `width`/`height` attributes on the portrait are nominal (CSS sets size and 4:5 crop); adjust to the
real file if desired. Omit the email `<li>` if no email is set.

## Build notes

- `base.html` placeholders: `$title $description $canonical $name $nav $content $year $built_iso $built`.
- Publication venue variants: articles `<em>Journal</em>, vol(issue), pages.`; book chapters
  `In G. Foster (Ed.), <em>Book title</em>.`; a `note` field (e.g. "Advance online publication") follows as its own sentence.
- `--` in TOML year ranges and `--` in bib pages become en dashes. `canonical` links and `sitemap.xml` appear only if `base_url` is set.

- Fonts are self-hosted in `static/fonts/` (0xPropo Medium, 0xProto Bold; latin subsets, OFL texts alongside) and declared in `style.css`. Home intro: portrait sits in the left label column, name/position/bio/contact in the right column, matching the `group` grid.
