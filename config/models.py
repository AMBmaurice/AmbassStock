from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import timedelta

class Produit(models.Model):
    reference = models.CharField(max_length=100, unique=True)
    objet = models.CharField(max_length=200)
    quantite = models.IntegerField(default=0)
    categorie = models.CharField(max_length=100)
    emplacement = models.CharField(max_length=100, blank=True, null=True)

    # Quota personnalisé (par défaut à 5)
    quota_minimum = models.IntegerField(default=5)
    # Pour le quota adaptatif dans le temps
    derniere_activite = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.objet

    @property
    def statut(self):
        # Si le quota n'est pas défini, on met la puce au vert par défaut
        if self.quota_minimum is None:
            return 'green'
            
        # ALERTE ROUGE : Stock inférieur ou égal au quota minimum
        if self.quantite <= self.quota_minimum:
            return 'red'
            
        # ZONE JAUNE : Stock proche de la rupture (quota + 10 articles restants)
        elif self.quantite <= (self.quota_minimum + 10):
            return 'yellow'
            
        # TOUT EST VERT
        else:
            return 'green'

class ProfilUtilisateur(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profil')
    nom_complet = models.CharField(max_length=150)
    mot_de_passe_clair = models.CharField(max_length=128, default="")
    acces_inventaire = models.BooleanField(default=False)
    acces_stocks = models.BooleanField(default=False)
    acces_historique = models.BooleanField(default=False)
    acces_statistiques = models.BooleanField(default=False)
    acces_gestion_demandes = models.BooleanField(default=False)
    acces_gestion_utilisateurs = models.BooleanField(default=False)
    acces_factures = models.BooleanField(default=False)
    type_profil = models.CharField(max_length=20, default='services')

    def __str__(self):
        return self.nom_complet

class DeclarationHebdomadaire(models.Model):
    CHOIX_SERVICES = [
        ('Consulaire', 'Consulaire'),
        ('Secrétaire', 'Secrétaire'),
        ('Secrétaire AMB', 'Secrétaire AMB'),
        ('1ère Secrétaire', '1ère Secrétaire'),
        ('2ème Secrétaire', '2ème Secrétaire'),
        ('Diplomate', 'Diplomate'),
        ('Administration', 'Administration'),
    ]

    CHOIX_REPONSES = [
        ('pris', "Je certifie avoir pris des éléments dans la réserve et les avoir enregistrés sur la plateforme."),
        ('rien', "Je certifie ne rien avoir pris cette semaine."),
    ]

    service = models.CharField(max_length=50, choices=CHOIX_SERVICES, unique=True)
    statut = models.CharField(max_length=20, default='en_attente')  
    reponse = models.CharField(max_length=10, choices=CHOIX_REPONSES, blank=True, null=True)
    date_validation = models.DateTimeField(blank=True, null=True)
    force_valide_par_admin = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.service} - {self.statut}"

class DemandeService(models.Model):
    CHOIX_TYPES = [
        ('suggestion', 'Une suggestion'),
        ('reapprovisionnement', 'Un réapprovisionnement'),
        ('autre', 'Autre'),
    ]
    
    CHOIX_SERVICES = [
        ('Consulaire', 'Consulaire'),
        ('Secrétaire', 'Secrétaire'),
        ('Secrétaire AMB', 'Secrétaire AMB'),
        ('1ère Secrétaire', '1ère Secrétaire'),
        ('2ème Secrétaire', '2ème Secrétaire'),
        ('Diplomate', 'Diplomate'),
        ('Administration', 'Administration'),
    ]

    CHOIX_STATUTS = [
        ('en_attente', 'En attente'),
        ('lu', 'Lu'),
        ('valide', 'Validé'),
    ]

    type_demande = models.CharField(max_length=30, choices=CHOIX_TYPES)
    service = models.CharField(max_length=50, choices=CHOIX_SERVICES)
    date_demande = models.DateField()
    message = models.TextField()
    statut = models.CharField(max_length=20, choices=CHOIX_STATUTS, default='en_attente')
    reponse_admin = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.service} - {self.type_demande} ({self.statut})"

class Facture(models.Model):
    date_commande = models.DateField()
    montant_total = models.DecimalField(max_digits=10, decimal_places=2)
    fichier_facture = models.FileField(upload_to='factures/')

    def __str__(self):
        return f"Facture du {self.date_commande} - {self.montant_total}€"

class MouvementStock(models.Model):
    CHOIX_TYPES = [
        ('ENTREE', 'Entrée'),
        ('SORTIE', 'Sortie'),
    ]
    type_mouvement = models.CharField(max_length=10, choices=CHOIX_TYPES)
    objet = models.CharField(max_length=200)
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE, related_name='mouvements', null=True, blank=True)
    quantite = models.IntegerField()
    service = models.CharField(max_length=100, default="Administration")
    date_mouvement = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.type_mouvement} - {self.objet} ({self.quantite})"
