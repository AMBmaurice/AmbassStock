from django.contrib import admin
from django.urls import path
from .views import (
    page_connexion,
    page_accueil,
    page_inventaire,
    page_gestion_stocks,
    page_historique,
    page_statistiques,
    page_gestion_utilisateurs,
    page_gestion_demandes,
    page_factures,
    page_profil,
    page_deconnexion,
    **modifier_mouvement**
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', page_connexion, name='racine'),
    path('connexion/', page_connexion, name='connexion'),
    path('accueil/', page_accueil, name='accueil'),
    path('inventaire/', page_inventaire, name='inventaire'),
    path('gestion-stocks/', page_gestion_stocks, name='gestion_stocks'),
    path('historique/', page_historique, name='historique'),
    path('historique/modifier/<int:mouvement_id>/', modifier_mouvement, name='modifier_mouvement'),
    path('statistiques/', page_statistiques, name='statistiques'),
    path('gestion-utilisateurs/', page_gestion_utilisateurs, name='gestion_utilisateurs'),
    path('gestion-demandes/', page_gestion_demandes, name='gestion_demandes'),
    path('factures/', page_factures, name='factures'),
    path('mon-profil/', page_profil, name='page_profil'),
    path('deconnexion/', page_deconnexion, name='deconnexion'),
]
