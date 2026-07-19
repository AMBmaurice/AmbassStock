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
            
    # Application de la pagination par blocs de 20 lignes
    paginator_entrees = Paginator(liste_entrees, 20)
    page_entrees = request.GET.get('page_entrees', 1)
    page_obj_entrees = paginator_entrees.get_page(page_entrees)

    paginator_sorties = Paginator(liste_sorties, 20)
    page_sorties = request.GET.get('page_sorties', 1)
    page_obj_sorties = paginator_sorties.get_page(page_sorties)

    return render(request, 'historique.html', {   
        'profil_actif': profil_actif,
        'page_obj_entrees': page_obj_entrees,
        'page_obj_sorties': page_obj_sorties,
        'entrees': page_obj_entrees.object_list,
        'sorties': page_obj_sorties.object_list
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
    
    # Période temporelle de base
    maintenant = timezone.now()
    
    # Paramètres dédiés uniquement à la consultation en direct à l'écran
    filter_year = int(request.GET.get('filter_year', maintenant.year))
    filter_month_raw = request.GET.get('filter_month', str(maintenant.month))

    # Paramètres pour le formulaire de génération de PDF (indépendants)
    annee_selectionnee = int(request.GET.get('target_year', maintenant.year))
    mois_selectionne_raw = request.GET.get('target_month', str(maintenant.month))

    # Listes pour alimenter les menus déroulants
    liste_annees = [maintenant.year, maintenant.year - 1, maintenant.year - 2]
    liste_mois = [
        {'valeur': 'all', 'nom': 'Total Annuel'},
        {'valeur': '1', 'nom': 'Janvier'}, {'valeur': '2', 'nom': 'Février'},
        {'valeur': '3', 'nom': 'Mars'}, {'valeur': '4', 'nom': 'Avril'},
        {'valeur': '5', 'nom': 'Mai'}, {'valeur': '6', 'nom': 'Juin'},
        {'valeur': '7', 'nom': 'Juillet'}, {'valeur': '8', 'nom': 'Août'},
        {'valeur': '9', 'nom': 'Septembre'}, {'valeur': '10', 'nom': 'Octobre'},
        {'valeur': '11', 'nom': 'Novembre'}, {'valeur': '12', 'nom': 'Décembre'}
    ]

    # Les statistiques de l'écran se basent sur filter_year et filter_month
    mouvements = MouvementStock.objects.filter(date_mouvement__year=filter_year)
    if filter_month_raw != 'all':
        filter_month = int(filter_month_raw)
        mouvements = mouvements.filter(date_mouvement__month=filter_month)
    else:
        filter_month = 'all'

    # 1. Indicateurs d'activité globaux
    total_operations = mouvements.count()
    total_entrees = mouvements.filter(type_mouvement='ENTREE').aggregate(total=Sum('quantite'))['total'] or 0
    total_sorties = mouvements.filter(type_mouvement='SORTIE').aggregate(total=Sum('quantite'))['total'] or 0
    
    # Correction de la rotation : calcul basé sur le stock global disponible pour éviter le zéro constant
    stock_total_disponible = Produit.objects.aggregate(total=Sum('quantite'))['total'] or 1
    taux_rotation = round((total_sorties / stock_total_disponible * 100), 1)

    # 2. Filtrage et génération du graphique principal (Bar Chart)
    view_mode = request.GET.get('view_mode', 'hebdomadaire')
    
    # Rendu dynamique basé sur les filtres de consultation de l'écran
    if view_mode == 'mensuel' and filter_month != 'all':
        import calendar
        nb_jours = calendar.monthrange(filter_year, filter_month)[1]
        jours = list(range(1, nb_jours + 1))
        chart_labels = [f"{j}" for j in jours]
        
        chart_sorties = []
        chart_operations = []
        for j in jours:
            mouvements_jour = mouvements.filter(date_mouvement__day=j)
            quantite_sortie = mouvements_jour.filter(type_mouvement='SORTIE').aggregate(s=Sum('quantite'))['s'] or 0
            chart_sorties.append(quantite_sortie)
            chart_operations.append(mouvements_jour.count())
            
    elif view_mode == 'mensuel' and filter_month == 'all':
        chart_labels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc']
        chart_sorties = []
        chart_operations = []
        for m in range(1, 13):
            mouvements_mois = MouvementStock.objects.filter(date_mouvement__year=filter_year, date_mouvement__month=m)
            chart_sorties.append(mouvements_mois.filter(type_mouvement='SORTIE').aggregate(s=Sum('quantite'))['s'] or 0)
            chart_operations.append(mouvements_mois.count())
            
    else:
        debut_semaine = maintenant.date() - timedelta(days=6)
        jours = [debut_semaine + timedelta(days=i) for i in range(7)]
        chart_labels = [j.strftime('%d %b') for j in jours]
        
        chart_sorties = [MouvementStock.objects.filter(type_mouvement='SORTIE', date_mouvement=j).aggregate(s=Sum('quantite'))['s'] or 0 for j in jours]
        chart_operations = [MouvementStock.objects.filter(date_mouvement=j).count() for j in jours]

    # 3. Consommation par service
    sorties_par_service = mouvements.filter(type_mouvement='SORTIE').values('service').annotate(total=Sum('quantite')).order_by('-total')
    service_labels = [s['service'] for s in sorties_par_service]
    service_data = [s['total'] for s in sorties_par_service]

    # 4. Répartition par catégorie
    sorties_par_cat = mouvements.filter(type_mouvement='SORTIE', produit__isnull=False).values('produit__categorie').annotate(total=Sum('quantite')).order_by('-total')
    category_labels = [c['produit__categorie'] for c in sorties_par_cat]
    category_data = [c['total'] for c in sorties_par_cat]

    # 5. Top 3 & Flop 3 des ventes
    produits_analytics = mouvements.filter(type_mouvement='SORTIE').values('objet').annotate(total_sorti=Sum('quantite'))
    pas_de_donnees_mouvement = not produits_analytics.exists()

    top_produits = produits_analytics.order_by('-total_sorti')[:3]
    flop_produits = produits_analytics.order_by('total_sorti')[:3]

    # 6. Produits dormants (Aucune activité depuis 6 mois)
    seuil_dormant = maintenant - timedelta(days=180)
    produits_dormants = Produit.objects.filter(derniere_activite__lte=seuil_dormant).order_by('objet')

    # Ajustement pour la comparaison de chaînes au format brut
    mois_selectionne = mois_selectionne_raw

    return render(request, 'statistiques.html', {
        'profil_actif': profil_actif,
        'total_operations': total_operations,
        'total_entrees': total_entrees,
        'total_sorties': total_sorties,
        'taux_rotation': taux_rotation,
        'view_mode': view_mode,
        'filter_year': filter_year,
        'filter_month': filter_month,
        'annee_selectionnee': annee_selectionnee,
        'mois_selectionne': mois_selectionne,
        'liste_annees': liste_annees,
        'liste_mois': liste_mois,
        'chart_labels': chart_labels,
        'chart_sorties': chart_sorties,
        'chart_operations': chart_operations,
        'service_labels': service_labels,
        'service_data': service_data,
        'category_labels': category_labels,
        'category_data': category_data,
        'pas_de_donnees_mouvement': pas_de_donnees_mouvement,
        'top_produits': top_produits,
        'flop_produits': flop_produits,
        'produits_dormants': produits_dormants
    })
    
def page_factures(request):
    if not request.user.is_authenticated:
        return redirect('/connexion/')
    profil_actif = get_profil_actif(request.user)
    
    if request.method == "POST":
        date_commande = request.POST.get('date_facture')
        montant_total = request.POST.get('montant')
        
        # Le fichier physique envoyé par le formulaire
        fichier_facture = request.FILES.get('fichier_facture')
        
        if not date_commande:
            from datetime import date
            date_commande = date.today()
        
        if montant_total and fichier_facture:
            try:
                # On utilise uniquement les champs validés et existants de ton modèle
                # pour garantir le fonctionnement immédiat du cloud Supabase
                Facture.objects.create(
                    date_commande=date_commande,
                    montant_total=float(montant_total),
                    fichier_facture=fichier_facture
                )
            except Exception:
                pass
            return redirect('/factures/')

    toutes_les_factures = Facture.objects.all().order_by('-date_commande', '-id')
    
    return render(request, 'factures.html', {
        'profil_actif': profil_actif,
        'factures': toutes_les_factures
    })
    
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

# AJOUT DANS VIEWS.PY : Contrôleur de génération des rapports d'audit personnalisés
def generer_pdf_statistiques(request):
    if not request.user.is_authenticated:
        return redirect('/connexion/')
    
    profil_actif = get_profil_actif(request.user)
    maintenant = timezone.now()

    # Extraction des configurations du périmètre du rapport
    type_analyse = request.GET.get('type_analyse', 'mensuel')
    inclure_graphiques = request.GET.get('inclure_graphiques') == 'true'
    inclure_dormants = request.GET.get('inclure_dormants') == 'true'
    inclure_remarques = request.GET.get('inclure_remarques') == 'true'

    # Variables temporelles cibles pour filtrer l'historique
    target_year = int(request.GET.get('target_year', maintenant.year))
    target_month_raw = request.GET.get('target_month', str(maintenant.month))

    # Traitement unifié des périodes pour l'affichage textuel du rapport
    if target_month_raw != 'all':
        target_month = int(target_month_raw)
        periode_a = f"{target_month}/{target_year}"
        mouvements = MouvementStock.objects.filter(date_mouvement__year=target_year, date_mouvement__month=target_month)
    else:
        target_month = 'all'
        periode_a = f"Année {target_year}"
        mouvements = MouvementStock.objects.filter(date_mouvement__year=target_year)

    # Variables de période de comparaison (pour les modes comparatifs)
    periode_b_raw = request.GET.get('periode_b', '')
    periode_b = periode_b_raw if periode_b_raw else None

    # 1. Calcul des indicateurs logistiques de base pour la période A
    total_operations = mouvements.count()
    total_entrees = mouvements.filter(type_mouvement='ENTREE').aggregate(total=Sum('quantite'))['total'] or 0
    total_sorties = mouvements.filter(type_mouvement='SORTIE').aggregate(total=Sum('quantite'))['total'] or 0
    taux_rotation = round((total_sorties / total_entrees * 100), 1) if total_entrees > 0 else 0.0

    # Extraction des données de répartition (Donuts)
    sorties_par_service = mouvements.filter(type_mouvement='SORTIE').values('service').annotate(total=Sum('quantite')).order_by('-total')
    service_labels = [s['service'] for s in sorties_par_service]
    service_data = [s['total'] for s in sorties_par_service]

    sorties_par_cat = mouvements.filter(type_mouvement='SORTIE', produit__isnull=False).values('produit__categorie').annotate(total=Sum('quantite')).order_by('-total')
    category_labels = [c['produit__categorie'] for c in sorties_par_cat]
    category_data = [c['total'] for c in sorties_par_cat]

    # Extraction des matériels dormants (sans flux depuis plus de 180 jours)
    seuil_dormant = maintenant - timedelta(days=180)
    produits_dormants = Produit.objects.filter(derniere_activite__lte=seuil_dormant).order_by('objet')
    
    # Qualification du statut d'immobilisation
    statut_dormant = "Optimal" if produits_dormants.count() <= 5 else "Vigilance Requise"
    statut_general = "Activité Stable" if total_operations > 10 else "Activité Faible"

    # Initialisation des variables spécifiques aux structures de rapports
    kpis_avances = []
    tableau_specifique = None
    synthese_generale = "Aucun mouvement significatif enregistré sur cette période pour formuler un audit."
    remarque_sectorielle = "Les données de consommation sectorielles sont équilibrées."
    remarque_dormant = "Le volume de stockage passif ne présente pas d'anomalie critique."

    # ==========================================
    # STRUCTURE 1 : AUDIT MENSUEL SPÉCIFIQUE
    # ==========================================
    if type_analyse == 'mensuel':
        score_intensite = round(total_sorties / total_operations, 1) if total_operations > 0 else 0
        kpis_avances = [
            {"nom": "Score d'Intensité (Volume moyen par retrait)", "valeur": f"{score_intensite} unités", "seuil": "Fux réguliers", "diag": "Valide"},
            {"nom": "Indice de Flux Tendus (Entrées vs Sorties)", "valeur": f"{total_entrees} entrées / {total_sorties} sorties", "seuil": "Équilibre requis", "diag": "Flux Ajustés"}
        ]
        
        # Calcul automatique des articles menacés de rupture sous 15 jours
        alertes_approvisionnement = []
        for p in Produit.objects.all():
            sorties_mensuelles = mouvements.filter(type_mouvement='SORTIE', produit=p).aggregate(s=Sum('quantite'))['s'] or 0
            vitesse_consommation_15j = sorties_mensuelles / 2
            if p.quantite <= vitesse_consommation_15j and sorties_mensuelles > 0:
                alertes_approvisionnement.append({"reference": p.reference, "objet": p.objet, "stock": p.quantite, "consomme": sorties_mensuelles})
        
        tableau_specifique = {"type": "alertes_mensuelles", "donnees": alertes_approvisionnement}
        
        # Rédaction des conclusions opérationnelles mensuelles
        if total_sorties > 0:
            service_majoritaire = service_labels[0] if service_labels else "aucun"
            synthese_generale = f"L'audit du mois indique une activité concentrée sur le service {service_majoritaire}. Le rythme des sorties impose un contrôle strict des stocks physiques au début du mois prochain."
            remarque_sectorielle = f"Le pôle majeur de consommation de ce mois est représenté par la catégorie {category_labels[0] if category_labels else 'non définie'}."
            remarque_dormant = f"Il est recommandé d'apurer les {produits_dormants.count()} références inactives pour libérer de l'espace pour les consommables à forte rotation."

    # ==========================================
    # STRUCTURE 2 : BILAN ANNUEL SPÉCIFIQUE
    # ==========================================
    elif type_analyse == 'annuel':
        estimation_encombrement = produits_dormants.aggregate(t=Sum('quantite'))['t'] or 0
        kpis_avances = [
            {"nom": "Volume Annuel Immobilisé Inactif", "valeur": f"{estimation_encombrement} unités", "seuil": "Inférieur à 200", "diag": "Alerte Espace" if estimation_encombrement > 200 else "Conforme"},
            {"nom": "Taux d'Utilisation des Stocks Passifs", "valeur": "0.0%", "seuil": "Objectif de réduction", "diag": "Perte Sèche"}
        ]
        
        # Construction du palmarès complet d'efficacité annuelle des services
        palmares = []
        for s in sorties_par_service:
            palmares.append({"service": s['service'], "total": s['total'], "part": round((s['total'] / total_sorties * 100), 1) if total_sorties > 0 else 0})
        
        tableau_specifique = {"type": "palmares_annuel", "donnees": palmares}
        
        # Rédaction des conclusions budgétaires annuelles
        synthese_generale = f"Le bilan logistique annuel montre un volume total cumulé de {total_operations} fiches d'opérations. Le taux de rotation global s'établit à {taux_rotation}%, révélant la performance de la chaîne d'approvisionnement."
        remarque_sectorielle = "L'analyse macroscopique sur 12 mois démontre une dépendance structurelle aux consommables de bureau et d'administration."
        remarque_dormant = f"L'immobilisation prolongée de {produits_dormants.count()} références représente un coût d'opportunité spatial pour la réserve de la délégation."

    # ==========================================
    # STRUCTURE 3 : COMPARAISON ÉVOLUTION (MOIS A VS MOIS B)
    # ==========================================
    elif type_analyse == 'comparaison_mois':
        mois_b_data = {"entrees": 0, "sorties": 0, "ops": 0}
        if periode_b:
            try:
                date_b = datetime.strptime(periode_b, "%Y-%m")
                mouv_b = MouvementStock.objects.filter(date_mouvement__year=date_b.year, date_mouvement__month=date_b.month)
                mois_b_data["ops"] = mouv_b.count()
                mois_b_data["entrees"] = mouv_b.filter(type_mouvement='ENTREE').aggregate(t=Sum('quantite'))['t'] or 0
                mois_b_data["sorties"] = mouv_b.filter(type_mouvement='SORTIE').aggregate(t=Sum('quantite'))['t'] or 0
            except ValueError:
                pass

        ecart_sorties = total_sorties - mois_b_data["sorties"]
        pct_evolution = round((ecart_sorties / mois_b_data["sorties"] * 100), 1) if mois_b_data["sorties"] > 0 else 0
        tendance_txt = f"+{pct_evolution}%" if pct_evolution >= 0 else f"{pct_evolution}%"

        kpis_avances = [
            {"nom": "Évolution Relative des Sorties", "valeur": tendance_txt, "seuil": "Objectif Sobriété", "diag": "En Hausse" if pct_evolution > 0 else "En Baisse"},
            {"nom": "Variation Volumétrique des Fiches", "valeur": f"{total_operations - mois_b_data['ops']} unités", "seuil": "Stabilité visée", "diag": "Ajusté"}
        ]

        # Tableau des écarts relatifs par catégorie
        ecarts_categories = []
        for cat in list(set(category_labels)):
            q_a = mouvements.filter(type_mouvement='SORTIE', produit__categorie=cat).aggregate(t=Sum('quantite'))['t'] or 0
            q_b = 0
            if periode_b:
                q_b = MouvementStock.objects.filter(type_mouvement='SORTIE', date_mouvement__year=date_b.year, date_mouvement__month=date_b.month, produit__categorie=cat).aggregate(t=Sum('quantite'))['t'] or 0
            ecarts_categories.append({"categorie": cat, "mois_a": q_a, "mois_b": q_b, "ecart": q_a - q_b})

        tableau_specifique = {"type": "ecarts_mensuels", "donnees": ecarts_categories}

        # Rédaction comparative de court terme
        synthese_generale = f"La comparaison directe montre une variation d'activité de {tendance_txt} du volume de matériel retiré entre la période de référence et la période de comparaison."
        remarque_sectorielle = "L'analyse met en relief des oscillations de consommation sectorielles dictées par l'agenda des événements diplomatiques."
        remarque_dormant = "Les stocks passifs sont restés rigoureusement inchangés entre les deux mois audités."

    # ==========================================
    # STRUCTURE 4 : COMPARAISON INTERANNUELLE (ANNÉE A VS ANNÉE B)
    # ==========================================
    elif type_analyse == 'comparaison_ans':
        annee_b_data = {"entrees": 0, "sorties": 0, "ops": 0}
        annee_b_target = target_year - 1
        if periode_b and len(periode_b) == 4:
            annee_b_target = int(periode_b)
        
        mouv_annee_b = MouvementStock.objects.filter(date_mouvement__year=annee_b_target)
        annee_b_data["ops"] = mouv_annee_b.count()
        annee_b_data["entrees"] = mouv_annee_b.filter(type_mouvement='ENTREE').aggregate(t=Sum('quantite'))['t'] or 0
        annee_b_data["sorties"] = mouv_annee_b.filter(type_mouvement='SORTIE').aggregate(t=Sum('quantite'))['t'] or 0
        rot_b = round((annee_b_data["sorties"] / annee_b_data["entrees"] * 100), 1) if annee_b_data["entrees"] > 0 else 0

        kpis_avances = [
            {"nom": "Évolution Efficience Globale (Taux Rotation)", "valeur": f"{taux_rotation}% vs {rot_b}%", "seuil": "Progression attendue", "diag": "Optimisé" if taux_rotation >= rot_b else "Régression"},
            {"nom": "Variation structurelle des flux", "valeur": f"{total_operations - annee_b_data['ops']} opérations", "seuil": "Suivi long terme", "diag": "Évolution Constatée"}
        ]

        # Bilan de trajectoire annuel condensé
        trajectoire = [
            {"indicateur": "Opérations globales", "annee_a": total_operations, "annee_b": annee_b_data["ops"], "evolution": total_operations - annee_b_data["ops"]},
            {"indicateur": "Volume total entré", "annee_a": total_entrees, "annee_b": annee_b_data["entrees"], "evolution": total_entrees - annee_b_data["entrees"]},
            {"indicateur": "Volume total sorti", "annee_a": total_sorties, "annee_b": annee_b_data["sorties"], "evolution": total_sorties - annee_b_data["sorties"]}
        ]
        
        tableau_specifique = {"type": "trajectoire_annuelle", "donnees": trajectoire}
        periode_b = f"Année {annee_b_target}"

        # Rédaction macro pour la direction
        synthese_generale = f"L'analyse pluriannuelle objective une transformation des trajectoires de flux. L'écart net d'opérations s'établit à {total_operations - annee_b_data['ops']} fiches sur les cycles comparés."
        remarque_sectorielle = "Les glissements de consommation interannuels traduisent une rationalisation progressive des achats de fournitures de la délégation."
        remarque_dormant = "La pérennité de certaines poches d'inactivité dans le stock sur 24 mois nécessite la mise en place d'un protocole d'apurement global."

    # Rendu final vers le template HTML d'impression
    return render(request, 'rapport_statistiques.html', {
        'profil_actif': profil_actif,
        'type_analyse': type_analyse,
        'periode_a': periode_a,
        'periode_b': periode_b,
        'total_operations': total_operations,
        'taux_rotation': taux_rotation,
        'total_entrees': total_entrees,
        'total_sorties': total_sorties,
        'statut_general': statut_general,
        'statut_dormant': statut_dormant,
        'produits_dormants': produits_dormants,
        'inclure_graphiques': inclure_graphiques,
        'inclure_dormants': inclure_dormants,
        'inclure_remarques': inclure_remarques,
        'service_labels': service_labels,
        'service_data': service_data,
        'category_labels': category_labels,
        'category_data': category_data,
        'kpis_avances': kpis_avances,
        'tableau_specifique': tableau_specifique,
        'synthese_generale': synthese_generale,
        'remarque_sectorielle': remarque_sectorielle,
        'remarque_dormant': remarque_dormant,
    })
