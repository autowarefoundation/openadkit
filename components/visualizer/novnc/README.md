# noVNC look

`openadkit.css` gives noVNC the Autoware Foundation brand guideline's black
theme; the Dockerfile links it after noVNC's `base.css`, points the favicons at
`icons/` and sets the page title. noVNC's code is unchanged, its name stays as
"powered by noVNC" under the connect button, and its license files stay in the
image (`/usr/share/doc/novnc/copyright`: MPL-2.0 for the code, BSD-2-Clause for
HTML and CSS, CC-BY-SA-3.0 for its images).

`autoware-logo-white.png` is the Autoware Foundation's logo from its brand kit,
unaltered. `autoware-symbol-white.png` is the logo's symbol, cut out of it
unscaled, and `icons/` carries that symbol, white on black with clear space, at
the sizes noVNC links; the guideline itself uses the symbol on its own. The
logo and the symbol are trademarks of the Autoware Foundation and are not
covered by this repository's license; they are used under the foundation's
[trademark policy](https://autoware.org/autoware-trademark-policy/) and
[brand guideline](https://autoware.org/wp-content/uploads/2023/06/Brand-Guideline-THE-AUTOWARE-FOUNDATION.pdf).
