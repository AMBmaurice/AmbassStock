from django.contrib import admin
from django.urls import path
from config import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.page_connexion, name='connexion'),
    path('connexion/', views.page_connexion, name='connexion'),
    path('deconnexion/', views.page_connexion, name='deconnexion'),
    path('accueil/', views.page_accueil, name='accueil'),
    
    # Redirections de sécurité pour éviter les erreurs 404 sur les pages non configurées
    path('statistiques/', views.page_accueil, name='statistiques'),
    path('demandes/', views.page_accueil, name='gestion_demandes'),
    path('factures/', views.page_accueil, name='factures'),
    path('utilisateurs/', views.page_accueil, name='gestion_utilisateurs'),
    
    # Routes actives de l'application
    path('inventaire/', views.page_inventaire, name='inventaire'),
    path('inventaire', views.page_inventaire),
    
    path('gestion-stocks/', views.page_gestion_stocks, name='gestion_stocks'),
    path('gestion-stocks', views.page_gestion_stocks),
    
    path('historique/', views.page_historique, name='historique'),
    path('historique', views.page_historique),
    
    path('supprimer-mouvement/<int:mouvement_id>/', views.supprimer_mouvement, name='supprimer_mouvement'),
]
