from django.contrib import admin
from django.urls import path
from config import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.page_connexion, name='connexion'),
    path('connexion/', views.page_connexion, name='connexion'),
    path('accueil/', views.page_accueil, name='accueil'),
    path('inventaire/', views.page_inventaire, name='inventaire'),
    path('gestion-stocks/', views.page_gestion_stocks, name='gestion_stocks'),
    path('historique/', views.page_historique, name='historique'),
    path('supprimer-mouvement/<int:mouvement_id>/', views.supprimer_mouvement, name='supprimer_mouvement'),
]
