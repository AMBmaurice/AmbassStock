import io
import re
import unicodedata
from datetime import date, datetime, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Sum, Count, Q
from django.contrib import messages
from django.views.decorators.http import require_POST

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from django.http import HttpResponse
from .models import Produit


from .models import Produit, ProfilUtilisateur, DeclarationHebdomadaire, DemandeService, Facture, MouvementStock

def get_profil_actif(user):
    if not user.is_authenticated:
        return None

    if user.is_superuser:
        class ProfilAdmin:
            acces_inventaire = True
            acces_stocks = True
            acces_historique = True
            acces_statistiques = True
            acces_gestion_utilisateurs = True
            acces_factures = True

        return ProfilAdmin()

    try:
        return ProfilUtilisateur.objects.get(user=user)
    except ProfilUtilisateur.DoesNotExist:
        return None

def page_connexion(request):
    if request.user.is_authenticated: 
        return redirect('/accueil/')

    if request.method == "POST":
        nom_utilisateur = request.POST.get('username')
        if nom_utilisateur:
            nom_utilisateur = nom_utilisateur.strip()
            
        mot_de_passe = request.POST.get('password')

        user = authenticate(request, username=nom_utilisateur, password=mot_de_passe)
    
        if user is not None:
            login(request, user)
            return redirect('/accueil/')
        else:
            return render(request, 'connexion.html', {'erreur': 'Identifiant ou mot de passe incorrect.'})
            
    return render(request, 'connexion.html')

def page_accueil(request):
    if not request.user.is_authenticated:
        return redirect('/connexion/')
        
    try:
        profil_actif = get_profil_actif(request.user)
    except Exception:
        profil_actif = None
        
    est_role_admin = request.user.is_superuser or (
        profil_actif and (
            getattr(profil_actif, 'type_profil', '') == 'admin' or 
            getattr(profil_actif, 'role', '') == 'Administrateur'
        )
    )
    
    maintenant = timezone.now()
    jour_semaine = maintenant.weekday()
    heure_actuelle = maintenant.hour
            
    liste_des_services = [
        "Consulaire",
        "Secrétaire",
        "Secrétaire AMB",
        "1ère Secrétaire",
        "2ème Secrétaire",
        "Diplomate",
        "Administration"
    ]
    for nom_service in liste_des_services:
        DeclarationHebdomadaire.objects.get_or_create(service=nom_service)
            
    if jour_semaine == 2 and heure_actuelle == 0:
        DeclarationHebdomadaire.objects.all().update(
            statut='en_attente',
            reponse=None,
            date_validation=None,
            force_valide_par_admin=False
        )
    
    if (jour_semaine == 1 and heure_actuelle >= 10) or (jour_semaine == 2 and heure_actuelle < 0):
        DeclarationHebdomadaire.objects.filter(statut='en_attente').update(statut='en_retard')
    
    if request.method == "POST":
        if "soumettre_declaration" in request.POST:
            service_choisi = request.POST.get('service')
            reponse_choisie = request.POST.get('reponse')
            try:
                dec = DeclarationHebdomadaire.objects.get(service=service_choisi)
                dec.reponse = reponse_choisie
                dec.statut = 'valide'
                dec.date_validation = timezone.now()
                dec.save()
            except DeclarationHebdomadaire.DoesNotExist:
                pass
            return redirect('/accueil/')
     
        elif "valider_admin" in request.POST and est_role_admin:
            id_declaration = request.POST.get('declaration_id')
            try:
                dec = DeclarationHebdomadaire.objects.get(id=id_declaration)
                dec.statut = 'valide'
                dec.force_valide_par_admin = True
                dec.date_validation = timezone.now()
                dec.save()
            except DeclarationHebdomadaire.DoesNotExist:
                pass
            return redirect('/accueil/')
    
        elif "soumettre_demande" in request.POST and not est_role_admin:
            type_demande = request.POST.get('type_demande')
            service = request.POST.get('service_demande')
            date_demande = request.POST.get('date_demande')
            message = request.POST.get('message_demande')
            
            if type_demande and service and date_demande and message:
                DemandeService.objects.create(
                    type_demande=type_demande,
                    service=service, 
                    date_demande=date_demande,
                    message=message
                )
            return redirect('/accueil/')
            
    declarations_reelles = DeclarationHebdomadaire.objects.all()
        
    notification_alerte = None
    if not est_role_admin:
        for d in declarations_reelles:
            if d.statut == "en_retard":
                notification_alerte = f"Attention, il est temps de se régulariser pour le service {d.service} !"
                break
                
    page_obj_alerte = None
    if est_role_admin:
        liste_alerte = Produit.objects.filter(quantite__lte=F('quota_minimum')).order_by('objet')
        paginator_alerte = Paginator(liste_alerte, 10)
        page_number = request.GET.get('page_alerte')
        page_obj_alerte = paginator_alerte.get_page(page_number)
            
    return render(request, 'accueil.html', {
        'profil_actif': profil_actif,
        'declarations': declarations_reelles,
        'notification_alerte': notification_alerte,
        'is_admin': est_role_admin,
        'demandes': DemandeService.objects.all().order_by('-id'),
        'produits_alerte': page_obj_alerte
    })

def page_inventaire(request):
    profil_actif = get_profil_actif(request.user)
    if not request.user.is_authenticated:
        return redirect('/connexion/')
                
    if request.method == "POST":
        action_type = request.POST.get('action_type')
            
        if action_type == "modification":
            produit_id = request.POST.get('produit_id')
            
            current_page = request.POST.get('page', '1')
            recherche_term = request.POST.get('q', '')
            statut_filtre = request.POST.get('statut', 'all')
            tri_filtre = request.POST.get('tri', 'alpha')
            
            try:
                produit = Produit.objects.get(id=produit_id)
                produit.reference = request.POST.get('reference')
                produit.objet = request.POST.get('objet')
                produit.categorie = request.POST.get('categorie')
                produit.emplacement = request.POST.get('emplacement')
                produit.quantite = int(request.POST.get('quantite', 0))
                produit.quota_minimum = int(request.POST.get('quota_minimum', 0))
                produit.save()
            
                messages.success(request, f'Modification du produit "{produit.objet}" enregistrée avec succès !')
            except Produit.DoesNotExist:
                pass
            
            redirect_url = f'/inventaire/?page={current_page}'
            if recherche_term:
                redirect_url += f'&q={recherche_term}'
            if statut_filtre and statut_filtre != 'all':
                redirect_url += f'&statut={statut_filtre}'
            if tri_filtre and tri_filtre != 'alpha':
                redirect_url += f'&tri={tri_filtre}'
            
            return redirect(redirect_url)
            
        elif action_type == "suppression_definitive" and request.user.is_superuser:
            produit_id = request.POST.get('produit_id')
            current_page = request.POST.get('page', '1') 
            recherche_term = request.POST.get('q', '')
            statut_filtre = request.POST.get('statut', 'all')
            tri_filtre = request.POST.get('tri', 'alpha')   
                    
            try:
                produit = Produit.objects.get(id=produit_id)
                nom_produit_supprime = produit.objet
                produit.delete()
                
                messages.success(request, f'Le produit "{nom_produit_supprime}" a été supprimé définitivement.')
            except Produit.DoesNotExist:
                pass
            
            redirect_url = f'/inventaire/?page={current_page}'
            if recherche_term:
                redirect_url += f'&q={recherche_term}'
            if statut_filtre and statut_filtre != 'all':
                redirect_url += f'&statut={statut_filtre}'
            if tri_filtre and tri_filtre != 'alpha':
                redirect_url += f'&tri={tri_filtre}'
            
            return redirect(redirect_url)

        elif action_type == "generer_recapitulatif_pdf":
            import io
            from django.http import HttpResponse
            from django.utils import timezone
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            
            produits_actifs = Produit.objects.exclude(emplacement="Archivé").filter(quantite__gt=0).order_by('emplacement', 'objet')
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
            story = []
            
            styles = getSampleStyleSheet()
            style_titre = ParagraphStyle(
                'TitrePDF',
                parent=styles['Heading1'],
                fontName='Helvetica-Bold',
                fontSize=24,
                leading=28,
                textColor=colors.HexColor('#2C351C'),
                spaceAfter=10
            )
            style_meta = ParagraphStyle(
                'MetaPDF',
                parent=styles['Normal'],
                fontName='Helvetica',
                fontSize=10,
                textColor=colors.HexColor('#7A8278'),
                spaceAfter=25
            )
            style_cellule = ParagraphStyle(
                'CellPDF',
                parent=styles['Normal'],
                fontName='Helvetica',
                fontSize=10,
                leading=13
            )
            style_entete = ParagraphStyle(
                'HeaderPDF',
                parent=styles['Normal'],
                fontName='Helvetica-Bold',
                fontSize=10,
                leading=13,
                textColor=colors.white
            )
            
            date_generation = timezone.now().strftime('%d/%m/%Y à %H:%M')
            story.append(Paragraph("Récapitulatif officiel de l'inventaire", style_titre))
            story.append(Paragraph(f"Document généré le {date_generation} — Uniquement les articles disponibles en réserve", style_meta))
            
            donnees_table = [[
                Paragraph("Référence", style_entete),
                Paragraph("Désignation de l'objet", style_entete),
                Paragraph("Catégorie", style_entete),
                Paragraph("Emplacement", style_entete),
                Paragraph("Stock", style_entete)
            ]]
            
            for prod in produits_actifs:
                donnees_table.append([
                    Paragraph(prod.reference, style_cellule),
                    Paragraph(prod.objet, style_cellule),
                    Paragraph(prod.categorie, style_cellule),
                    Paragraph(prod.emplacement or "-", style_cellule),
                    Paragraph(str(prod.quantite), style_cellule)
                ])
            
            tableau_inventaire = Table(donnees_table, colWidths=[80, 160, 110, 120, 50])
            tableau_inventaire.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5E6D3E')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                ('TOPPADDING', (0, 0), (-1, 0), 10),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#FAFBF9'), colors.white]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E6E1')),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
                ('TOPPADDING', (0, 1), (-1, -1), 8),
            ]))
            
            story.append(tableau_inventaire)
            doc.build(story)
            
            buffer.seek(0)
            date_fichier = timezone.now().strftime('%Y_%m_%d')
            response = HttpResponse(buffer.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="Recapitulatif_Inventaire_{date_fichier}.pdf"'
            return response
            
    recherche_term = request.GET.get('q', '').strip()
    statut_filtre = request.GET.get('statut', 'all')
    tri_filtre = request.GET.get('tri', 'alpha')
            
    if tri_filtre == 'emplacement':
        tous_les_produits = Produit.objects.all().order_by('emplacement', 'objet')
    else:
        tous_les_produits = Produit.objects.all().order_by('objet')
                
    if recherche_term:
        tous_les_produits = tous_les_produits.filter(
            Q(objet__icontains=recherche_term) | Q(reference__icontains=recherche_term)
        )
                
    if statut_filtre and statut_filtre != 'all':
        produits_filtres_ids = []
        for p in tous_les_produits:
            if p.quota_minimum is not None:
                if p.quantite <= p.quota_minimum:
                    status = 'red'
                elif p.quantite <= (p.quota_minimum + 10):
                    status = 'yellow'
                else:
                    status = 'green'
            else:
                status = 'green'
            
            if status == statut_filtre:
                produits_filtres_ids.append(p.id)
    
        tous_les_produits = tous_les_produits.filter(id__in=produits_filtres_ids)
            
    tous_les_produits_complets = list(tous_les_produits)
        
    paginator = Paginator(tous_les_produits, 15)
    page_number = request.GET.get('page', '1')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'inventaire.html', {
        'profil_actif': profil_actif,
        'page_obj': page_obj,
        'tous_les_produits_complets': tous_les_produits_complets,
        'recherche_term': recherche_term,
        'statut_filtre': statut_filtre,
        'tri_filtre': tri_filtre   
    })

def page_gestion_stocks(request): 
    profil_actif = get_profil_actif(request.user)
    if not request.user.is_authenticated:
        return redirect('/connexion/')
                    
    COMPTEURS_DEPART = {
        'ECR': 26, 'BUR': 52, 'PAP': 32, 'CLA': 40,
        'CON': 35, 'INF': 17, 'ENV': 32, 'EQU': 18
    }
                    
    if request.method == "POST":
        action_type = request.POST.get('action_type')
                    
        if action_type == "creation" or action_type == "creation_produit":
            categorie_nom = request.POST.get('categorie')
            objet_nom = request.POST.get('objet') or request.POST.get('nom')
    
            match = re.search(r'\((.*?)\)', categorie_nom)
            code_categorie = match.group(1).upper() if match else "GEN"
    
            depart_historique = COMPTEURS_DEPART.get(code_categorie, 0)
            nb_existants = Produit.objects.filter(categorie=categorie_nom).count()
        
            prochain_numero = depart_historique + nb_existants + 1
            suffixe_numerique = f"{prochain_numero:02d}"
        
            marque_brute = request.POST.get('marque') or request.POST.get('marque_texte') or "GEN"
            spec_brute = request.POST.get('specification') or request.POST.get('spec_texte') or "MAG"

            def extraire_trigramme(texte):
                if not texte: return "XXX"
                clean = "".join(c for c in unicodedata.normalize('NFD', texte) if unicodedata.category(c) != 'Mn')
                clean = re.sub(r'[^a-zA-Z0-9]', '', clean).upper()
                return clean[:3].ljust(3, 'X') if len(clean) < 3 else clean[:3]
        
            code_marque = extraire_trigramme(marque_brute)
            code_spec = extraire_trigramme(spec_brute)
                
            reference_finale = f"{code_categorie}-{code_marque}-{code_spec}-{suffixe_numerique}"
            quantite_initiale = int(request.POST.get('quantite') or request.POST.get('quantite_initiale') or 0)
                    
            nouveau_produit = Produit.objects.create(
                reference=reference_finale,
                objet=objet_nom,
                categorie=categorie_nom,
                emplacement=request.POST.get('emplacement') or "Réserve",
                quantite=quantite_initiale,
                quota_minimum=int(request.POST.get('quota_minimum', 0))
            )
            
            if quantite_initiale > 0:
                MouvementStock.objects.create(
                    type_mouvement='ENTREE',
                    objet=objet_nom,
                    produit=nouveau_produit,
                    quantite=quantite_initiale,
                    service="Administration"
                )
                
            messages.success(request, "Nouveau produit ajouté à l'inventaire")
            return redirect('/gestion-stocks/')
        
        elif action_type == "mouvement_entree":
            ref_produit = request.POST.get('produit') 
            quantite_ajoutee = int(request.POST.get('quantite', 0))
            
            try:
                with transaction.atomic():
                    produit = Produit.objects.select_for_update().get(reference=ref_produit)
                    produit.quantite = F("quantite") + quantite_ajoutee
                    produit.save(update_fields=["quantite"])
                    produit.refresh_from_db()
                
                MouvementStock.objects.create(
                    type_mouvement='ENTREE',
                    objet=produit.objet,   
                    produit=produit,
                    quantite=quantite_ajoutee,
                    service="Administration",
                    date_mouvement=request.POST.get('date_entree') or date.today()
                )
                messages.success(request, "Quantité ajoutée")
            except Produit.DoesNotExist:
                pass
            return redirect('/gestion-stocks/')
                    
        elif action_type == "sortie":
            ref_produit = request.POST.get('produit')
            quantite_retiree = int(request.POST.get('quantite', 0))
            service_demandeur = request.POST.get('service') or "Administration"
        
            try:
                with transaction.atomic():
                    produit = Produit.objects.select_for_update().get(reference=ref_produit)

                    if produit.quantite < quantite_retiree:
                        messages.error(request, "Stock insuffisant.")
                        return redirect('/gestion-stocks/')

                    produit.quantite = F("quantite") - quantite_retiree
                    produit.save(update_fields=["quantite"])
                    produit.refresh_from_db()
                
                MouvementStock.objects.create(   
                    type_mouvement='SORTIE',
                    objet=produit.objet,
                    produit=produit,
                    quantite=quantite_retiree,
                    service=service_demandeur,
                    date_mouvement=request.POST.get('date_sortie') or date.today()
                )
                messages.success(request, "Quantité retirée")
            except Produit.DoesNotExist:
                pass
            return redirect('/gestion-stocks/')
            
        elif action_type == "archivage_produit":
            ref_produit = request.POST.get('produit_a_archiver')
            try:    
                produit = Produit.objects.get(reference=ref_produit)
                produit.delete()
                messages.success(request, "Produit supprimé")
            except Produit.DoesNotExist:
                pass
            return redirect('/gestion-stocks/')
                
    liste_produits = Produit.objects.all().order_by('objet')
    aujourd_hui = date.today().strftime('%Y-%m-%d')
                    
    return render(request, 'gestion_stocks.html', {
        'profil_actif': profil_actif,
        'produits': liste_produits,
        'date_du_jour': aujourd_hui
    })

def page_historique(request):
    profil_actif = get_profil_actif(request.user) 
    if not request.user.is_authenticated:
        return redirect('/connexion/')
                    
    flux_entrees = MouvementStock.objects.filter(type_mouvement='ENTREE').order_by('-id')
    flux_sorties = MouvementStock.objects.filter(type_mouvement='SORTIE').order_by('-id')
            
    entree_debut = request.GET.get('entree_debut')
    entree_fin = request.GET.get('entree_fin')  
    if entree_debut:
        flux_entrees = flux_entrees.filter(date_mouvement__gte=entree_debut)
    if entree_fin:
        flux_entrees = flux_entrees.filter(date_mouvement__lte=entree_fin)
                
    sortie_debut = request.GET.get('sortie_debut')
    sortie_fin = request.GET.get('sortie_fin')
    sortie_service = request.GET.get('sortie_service')
            
    if sortie_debut:
        flux_sorties = flux_sorties.filter(date_mouvement__gte=sortie_debut)
    if sortie_fin:  
        flux_sorties = flux_sorties.filter(date_mouvement__lte=sortie_fin)
    if sortie_service:
        flux_sorties = flux_sorties.filter(service=sortie_service)
        
    liste_entrees = list(flux_entrees)
    liste_sorties = list(flux_sorties)
        
    for movimiento in liste_entrees:
        if movimiento.produit:
            movimiento.objet = movimiento.produit.objet
            movimiento.reference = movimiento.produit.reference
    
    for movimiento in liste_sorties:   
        if movimiento.produit:
            movimiento.objet = movimiento.produit.objet
            movimiento.reference = movimiento.produit.reference
            
    return render(request, 'historique.html', {   
        'profil_actif': profil_actif,
        'entrees': liste_entrees,
        'sorties': liste_sorties
    })

@require_POST
def supprimer_mouvement(request, mouvement_id):
    if not request.user.is_authenticated:
        return redirect('/connexion/')
    mouvement = get_object_or_404(MouvementStock, id=mouvement_id)
    mouvement.delete()
    messages.success(request, "Mouvement de test supprimé de l'historique.")
    return redirect('/historique/')

def page_statistiques(request):
    if not request.user.is_authenticated:
        return redirect('/connexion/')
    profil_actif = get_profil_actif(request.user)
    return render(request, 'statistiques.html', {'profil_actif': profil_actif})

def page_factures(request):
    if not request.user.is_authenticated:
        return redirect('/connexion/')
    profil_actif = get_profil_actif(request.user)
    return render(request, 'factures.html', {'profil_actif': profil_actif})

def page_gestion_demandes(request):
    if not request.user.is_authenticated:
        return redirect('/connexion/')
    profil_actif = get_profil_actif(request.user)
    return render(request, 'gestion_demandes.html', {'profil_actif': profil_actif})

def page_gestion_utilisateurs(request):
    if not request.user.is_authenticated:
        return redirect('/connexion/')
    profil_actif = get_profil_actif(request.user)
    return render(request, 'gestion_utilisateurs.html', {'profil_actif': profil_actif})

def page_deconnexion(request):
    logout(request)
    messages.success(request, "Vous avez été déconnecté avec succès.")
    return redirect('/connexion/')

def test_database(request):
    produit = Produit.objects.create(
        reference="TEST123",
        objet="Test",
        categorie="Test",
        quantite=1,
        emplacement="Test"
    )

    return HttpResponse(
        f"Produit créé avec l'ID {produit.id}"
    )
