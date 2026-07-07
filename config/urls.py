from django.contrib import admin
from django.urls import path
from config import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.page_connexion, name='connexion'),
    path('connexion/', views.page_connexion, name='connexion'),
    path('deconnexion/', views.page_connexion, name='deconnexion'),
    path('accueil/', views.page_accueil, name='accueil'),
    
    # Redirections de sécurité temporaires vers l'accueil (évite les 404)
    path('statistiques/', views.page_accueil, name='statistiques'),
    path('factures/', views.page_accueil, name='factures'),
    
    # Alignement exact avec les chemins de tes boutons (gestion-demandes/ et gestion-utilisateurs/)
    path('gestion-demandes/', views.page_accueil, name='gestion_demandes'),
    path('gestion-utilisateurs/', views.page_accueil, name='gestion_utilisateurs'),
    
    # Routes actives de ton application AmbassStock
    path('inventaire/', views.page_inventaire, name='inventaire'),
    path('inventaire', views.page_inventaire),
    
    path('gestion-stocks/', views.page_gestion_stocks, name='gestion_stocks'),
    path('gestion-stocks', views.page_gestion_stocks),
    
    path('historique/', views.page_historique, name='historique'),
    path('historique', views.page_historique),
    
    path('supprimer-mouvement/<int:mouvement_id>/', views.supprimer_mouvement, name='supprimer_mouvement'),
]
