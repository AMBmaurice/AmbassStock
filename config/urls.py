from django.contrib import admin
from django.urls import path
from config import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.page_connexion, name='connexion'),
    path('connexion/', views.page_connexion, name='connexion'),
    path('deconnexion/', views.page_deconnexion, name='deconnexion'),
    path('accueil/', views.page_accueil, name='accueil'),
    
    # Liens connectés aux vues de l'application
    path('statistiques/', views.page_statistiques, name='statistiques'),
    path('factures/', views.page_factures, name='factures'),
    path('factures/voir/<int:facture_id>/', views.afficher_facture, name='voir_facture'),
    path('gestion-demandes/', views.page_gestion_demandes, name='gestion_demandes'),
    path('gestion-utilisateurs/', views.page_gestion_utilisateurs, name='gestion_utilisateurs'),
    
    # Routes principales d'inventaire et stocks
    path('inventaire/', views.page_inventaire, name='inventaire'),
    path('inventaire', views.page_inventaire),
    
    path('gestion-stocks/', views.page_gestion_stocks, name='gestion_stocks'),
    path('gestion-stocks', views.page_gestion_stocks),
    
    path('historique/', views.page_historique, name='historique'),
    path('historique', views.page_historique),
    
    path('modifier-mouvement/<int:mouvement_id>/', views.page_historique, name='modifier_mouvement'),
    path('supprimer-mouvement/<int:mouvement_id>/', views.supprimer_mouvement, name='supprimer_mouvement'),
    path("test-db/", views.test_database),
    path('generer-pdf-statistiques/', views.generer_pdf_statistiques, name='generer_pdf_statistiques'),

    path('panier/', views.page_panier, name='panier'),
]
