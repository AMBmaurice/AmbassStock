#!/usr/bin/env bash
# exit on error
set -o errexit

# Installer les dépendances Python (Django, ReportLab, etc.)
pip install -r requirements.txt

# Rassembler tous les fichiers statiques (CSS, Images) dans le dossier staticfiles
python manage.py collectstatic --no-input

# Appliquer les nouvelles tables en base de données si nécessaire
python manage.py migrate