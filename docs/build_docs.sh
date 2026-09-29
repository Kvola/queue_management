#!/bin/bash
# Régénère les guides utilisateur : Markdown (docs/*.md) → HTML servi derrière
# la connexion (/queue/guide/<nom>, menu Aide) → PDF imprimables (docs/pdf/).
#
# Prérequis : pandoc sur la machine hôte ; wkhtmltopdf via l'image Docker
# du projet (odoo_nineteen-web). Usage : sh docs/build_docs.sh
set -e
cd "$(dirname "$0")/.."   # racine du module

mkdir -p docs/html docs/pdf

declare -a GUIDES=(
    "guide_agent|Guide de l'agent de guichet"
    "guide_responsable|Guide du responsable"
    "guide_administrateur|Guide de l'administrateur"
)

for entry in "${GUIDES[@]}"; do
    slug="${entry%%|*}"
    title="${entry##*|}"
    echo "→ ${slug}"
    pandoc "docs/${slug}.md" -f gfm -t html5 -s \
        --metadata lang=fr --metadata "title=${title}" \
        -H docs/_style.html \
        -o "docs/html/${slug}.html"
    docker run --rm -v "$PWD":/work --entrypoint wkhtmltopdf odoo_nineteen-web \
        -q --enable-local-file-access \
        --margin-top 18mm --margin-bottom 18mm \
        "/work/docs/html/${slug}.html" "/work/docs/pdf/${slug}.pdf"
done

echo "✅ HTML dans docs/html/, PDF dans docs/pdf/"
