from django.contrib import admin
from django.urls import path
from .views import (
    connexion_view, deconnexion_view, accueil_view, inventaire_view,
    gestion_stocks_view, historique_view, modifier_mouvement, supprimer_mouvement
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', connexion_view, name='connexion'),
    path('connexion/', connexion_view, name='connexion'),
    path('deconnexion/', deconnexion_view, name='deconnexion'),
    path('accueil/', accueil_view, name='accueil'),
    path('inventaire/', inventaire_view, name='inventaire'),
    path('gestion-stocks/', gestion_stocks_view, name='gestion_stocks'),
    path('historique/', historique_view, name='historique'),
    path('modifier-mouvement/<int:mouvement_id>/', modifier_mouvement, name='modifier_mouvement'),
    path('supprimer-mouvement/<int:mouvement_id>/', supprimer_mouvement, name='supprimer_mouvement'),
]
