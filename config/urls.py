from django.contrib import admin
from django.urls import path
from config import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.accueil_view, name='accueil'),
    path('accueil/', views.accueil_view, name='accueil'),
    path('inventaire/', views.inventaire_view, name='inventaire'),
    path('gestion-stocks/', views.gestion_stocks_view, name='gestion_stocks'),
    path('historique/', views.historique_view, name='historique'),
    path('modifier-mouvement/<int:mouvement_id>/', views.modifier_mouvement, name='modifier_mouvement'),
    path('supprimer-mouvement/<int:mouvement_id>/', views.supprimer_mouvement, name='supprimer_mouvement'),
]
