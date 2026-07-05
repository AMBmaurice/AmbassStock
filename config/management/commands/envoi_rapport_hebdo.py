from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.utils import timezone
from datetime import date, timedelta
# Importe les fonctions de ton fichier views.py pour éviter les doublons de logique
from config.views import executer_moteur_analyse, generer_pdf_rapport

class Command(BaseCommand):
    help = "Calcule et envoie de manière autonome le rapport d'audit hebdomadaire par e-mail"

    # Tarer l'adresse de destination officielle (Secrétariat, Administrateur...)
    EMAIL_DESTINATAIRE = "mathisfrancois28@gmail.com"

    def handle(self, *args, **options):
        aujourd_hui = date.today()
        # On calcule les indicateurs sur le mois et l'année en cours au moment de l'exécution
        annee = aujourd_hui.year
        mois = aujourd_hui.month
        
        mois_noms = {
            1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin",
            7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"
        }
        mois_nom = mois_noms.get(mois, "Courant")
        
        self.stdout.write("Exécution du moteur d'analyse déterministe...")
        analyse = executer_moteur_analyse(annee, mois)
        
        self.stdout.write("Compilation du document PDF officiel...")
        titre_rapport = "Rapport Automatique d'Audit Hebdomadaire"
        pdf_buffer = generer_pdf_rapport(titre_rapport, analyse, str(annee), mois_nom)
        
        self.stdout.write(f"Préparation de l'envoi de l'e-mail à {self.EMAIL_DESTINATAIRE}...")
        
        sujet = f"AmbassStock - Rapport Hebdomadaire Automatique du {aujourd_hui.strftime('%d/%m/%Y')}"
        message_corps = (
            "Bonjour,\n\n"
            "Veuillez trouver ci-joint le rapport d'audit hebdomadaire automatisé concernant l'état et les mouvements physiques des stocks de la réserve.\n\n"
            f"Statut général calculé : {analyse['appreciation']} (Score : {analyse['score']}/100).\n"
            f"Nombre d'opérations enregistrées ce mois-ci : {analyse['total_operations']}.\n\n"
            "Ce document a été généré de manière déterministe à partir des saisies de la plateforme.\n\n"
            "Cordialement,\n"
            "Le Système d'Audit AmbassStock"
        )
        
        email = EmailMessage(
            subject=sujet,
            body=message_corps,
            from_email="noreply@ambassstock.local",
            to=[self.EMAIL_DESTINATAIRE]
        )
        
        # Attachement du fichier binaire ReportLab
        email.attach(
            f"Rapport_Hebdo_{aujourd_hui.strftime('%Y_%m_%d')}.pdf",
            pdf_buffer.getvalue(),
            "application/pdf"
        )
        
        try:
            email.send(fail_silently=False)
            self.stdout.write(self.style.SUCCESS("Le rapport hebdomadaire a été transmis avec succès."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Échec de l'envoi du message : {str(e)}"))