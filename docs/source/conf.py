import datetime
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import generate_markdown

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "ReEDS"
copyright = "2024, NREL"
author = "NLR"

# --setup function to run generate_markdown.py on 'make html' ---------------------------------
def setup(app):
    app.connect("builder-inited", generate_markdown.main)

# -- General configuration ----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = ["myst_parser", "sphinxcontrib.bibtex", "sphinx_design"]

bibtex_bibfiles = ["references.bib"]  # exported from zotero using better bibtex
bibtex_reference_style = "author_year"
bibtex_default_style = "plain"

templates_path = ["_templates"]
exclude_patterns = []

suppress_warnings = ["myst.xref_missing", "myst.header"]

numfig = True  # auto number figures when true

# get GAMSLICE from environment variable
gamslice_secret = os.getenv("GAMSLICE", "")


myst_enable_extensions = ["substitution", "dollarmath", "html_image"]

myst_substitutions = {
    "gamslice": gamslice_secret,
    "cite_date_last_updated": datetime.date.today().strftime("%Y, %B"),
}

myst_footnote_transition = False

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = [
    "customtheme.css",
]

html_theme_options = {"navigation_depth": 3, "logo_only": True}

html_logo = "_static/reeds-logo-white.png"

html_favicon = "_static/reeds-icon.png"

html_last_updated_fmt = "%B %d, %Y"

# Custom formatting for dropdowns
sd_custom_directives = {
    "dropdown-color": {
        "inherit": "dropdown",
        "options": {
            "color": "primary",
            # "icon": "plus"
        },
    }
}

# More info on the RTD theme configuration can be found at:
# https://github.com/readthedocs/sphinx_rtd_theme/blob/7c9b1b5d391f6d7fae72274393eb25d1df96e546/docs/configuring.rst
