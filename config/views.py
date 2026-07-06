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
from django.db.models import F, Sum, Count, Q
from django.contrib import messages

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

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
            nom_utilisateur = nom_utilisateur.lower().strip()
            
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
                produit = Produit.objects.get(reference=ref_produit)
                produit.quantite += quantite_ajoutee 
                produit.save()
                
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
                produit = Produit.objects.get(reference=ref_produit)
                if produit.quantite >= quantite_retiree:
                    produit.quantite -= quantite_retiree
                    produit.save()
                
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
        
    for movimiento in flux_entrees:
        if movimiento.produit:
            movimiento.objet = movimiento.produit.objet
            movimiento.reference = movimiento.produit.reference

    for movimiento in flux_sorties:
        if movimiento.produit:
            movimiento.objet = movimiento.produit.objet
            movimiento.reference = movimiento.produit.reference
        
    return render(request, 'historique.html', {
        'profil_actif': profil_actif,
        'entrees': flux_entrees,
        'sorties': flux_sorties
    })

def executer_moteur_analyse(annee, mois):
    produits_actifs = Produit.objects.exclude(emplacement="Archivé")
    total_produits = produits_actifs.count()
    
    mouvements_periode = MouvementStock.objects.filter(
        date_mouvement__year=annee,
        date_mouvement__month=mois
    )
    
    sorties_periode = mouvements_periode.filter(type_mouvement='SORTIE')
    entreres_periode = mouvements_periode.filter(type_mouvement='ENTREE')
    
    total_mouvements = mouvements_periode.count()
    total_sorties = sorties_periode.aggregate(total=Sum('quantite'))['total'] or 0
    total_entrees = entreres_periode.aggregate(total=Sum('quantite'))['total'] or 0
    
    produits_en_rupture = []
    produits_sous_seuil = []
    
    for p in produits_actifs:
        if p.quantite == 0:
            produits_en_rupture.append(p)
        elif p.quota_minimum and p.quantite <= p.quota_minimum:
            produits_sous_seuil.append(p)
            
    nb_ruptures = len(produits_en_rupture)
    nb_sous_seuil = len(produits_sous_seuil)
    
    seuil_date_dormant = timezone.now() - timedelta(days=180)
    produits_dormants = produits_actifs.filter(derniere_activite__lte=seuil_date_dormant)
    nb_dormants = produits_dormants.count()
    
    stock_total_volume = produits_actifs.aggregate(total=Sum('quantite'))['total'] or 0
    taux_rotation = round((total_sorties / stock_total_volume) * 100, 1) if stock_total_volume > 0 else 0
    
    score = 100
    score -= (nb_ruptures * 12)
    score -= (nb_sous_seuil * 4)
    if taux_rotation < 5.0 and total_sorties > 0:
        score -= 10
    if nb_dormants > (total_produits * 0.3) and total_produits > 0:
        score -= 8
    score = max(0, min(100, score))
    
    if score >= 85:
        appreciation = "Stock très sain"
        couleur_statut = "#1E7E34"
    elif score >= 70:
        appreciation = "Stock stable"
        couleur_statut = "#5E6D3E"
    elif score >= 50:
        appreciation = "Stock sous surveillance"
        couleur_statut = "#D39E00"
    elif score >= 30:
        appreciation = "Stock nécessitant une intervention"
        couleur_statut = "#C82333"
    else:
        appreciation = "Stock critique"
        couleur_statut = "#721C24"
        
    observations = []
    recommandations = []
    
    if nb_ruptures > 0:
        observations.append(f"Présence de {nb_ruptures} référence(s) en rupture totale de stock, bloquant les demandes des services.")
        recommandations.append({"priorite": "Critique", "action": "Lancer un réapprovisionnement d'urgence pour les articles épuisés."})
    else:
        observations.append("Excellente maîtrise des ruptures : aucun produit n'est épuisé sur la période.")
        
    if nb_sous_seuil > 0:
        pct_seuil = round((nb_sous_seuil / total_produits) * 100, 1) if total_produits > 0 else 0
        observations.append(f"Il y a {nb_sous_seuil} produit(s) sous leur quota minimum de sécurité, soit {pct_seuil}% de la réserve.")
        if pct_seuil > 25:
            recommandations.append({"priorite": "Attention", "action": "Revoir à la hausse le rythme des achats généraux pour stabiliser les quotas."})
        else:
            recommandations.append({"priorite": "Conseil", "action": "Planifier une commande de routine pour les articles sous le seuil."})
            
    produits_sollicites = sorties_periode.values('objet', 'produit__reference', 'produit__id').annotate(total_sorti=Sum('quantite')).order_by('-total_sorti')
    for ps in produits_sollicites[:3]:
        try:
            if ps.get('produit__id'):
                prod_obj = produits_actifs.get(id=ps['produit__id'])
            else:
                prod_obj = produits_actifs.get(reference=ps['produit__reference'])
                
            if prod_obj.quota_minimum and prod_obj.quantite <= prod_obj.quota_minimum:
                observations.append(f"Anomalie détectée : La référence {prod_obj.objet} subit une forte demande ({ps['total_sorti']} unités sorties) mais son stock actuel est insuffisant.")
                recommandations.append({"priorite": "Urgent", "action": f"Ajuster le quota minimum et sécuriser l'approvisionnement de : {prod_obj.objet}."})
        except Produit.DoesNotExist:
            pass

    if nb_dormants > 0:
        volume_dormant = produits_dormants.aggregate(total=Sum('quantite'))['total'] or 0
        observations.append(f"Immobilisation détectée : {nb_dormants} produit(s) n'ont enregistré aucun mouvement depuis plus de 6 mois (Volume : {volume_dormant} unités).")
        recommandations.append({"priorite": "Information", "action": "Envisager un rééquilibrage ou un transfert des fournitures inutilisées pour désencombrer l'espace."})

    ordre_priorite = {"Critique": 0, "Urgent": 1, "Attention": 2, "Conseil": 3, "Information": 4}
    recommandations.sort(key=lambda x: ordre_priorite.get(x["priorite"], 5))

    return {
        'total_produits': total_produits,
        'total_operations': total_mouvements,
        'total_entrees': total_entrees,
        'total_sorties': total_sorties,
        'taux_rotation': taux_rotation,
        'score': score,
        'appreciation': appreciation,
        'couleur_statut': couleur_statut,
        'observations': observations,
        'recommandations': recommandations,
        'produits_dormants': produits_dormants[:10]
    }

def generer_pdf_rapport(titre_rapport, analyse, annee, mois_nom):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    style_titre = ParagraphStyle('TitreStyle', parent=styles['Heading1'], fontSize=22, textColor=colors.HexColor('#2C351C'), spaceAfter=20, fontName='Helvetica-Bold')
    style_sous_titre = ParagraphStyle('SubStyle', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor('#7A8278'), spaceAfter=25)
    style_section = ParagraphStyle('SecStyle', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#495430'), spaceBefore=15, spaceAfter=12, fontName='Helvetica-Bold')
    style_texte = ParagraphStyle('TexteStyle', parent=styles['Normal'], fontSize=10.5, textColor=colors.HexColor('#333333'), leading=14, spaceAfter=8)
    
    story.append(Paragraph(titre_rapport, style_titre))
    story.append(Paragraph(f"Période d'audit : {mois_nom} {annee} | Document officiel généré le {date.today().strftime('%d/%m/%Y')}", style_sous_titre))
    story.append(Spacer(1, 10))
    
    story.append(Paragraph("Synthèse de Performance Opérationnelle", style_section))
    story.append(Paragraph(f"Score Global de Gestion : {analyse['score']} / 100", style_texte))
    story.append(Paragraph(f"Appréciation de la réserve : {analyse['appreciation']}", style_texte))
    story.append(Spacer(1, 10))
    
    data_kpi = [
        ["Indicateur de suivi", "Valeur sur la période"],
        ["Opérations de sorties validées", str(analyse['total_operations'])],
        ["Volume total d'articles distribués", f"{analyse['total_sorties']} unités"],
        ["Volume total d'articles réceptionnés", f"{analyse['total_entrees']} unités"],
        ["Taux de rotation des stocks", f"{analyse['taux_rotation']} %"]
    ]
    t_kpi = Table(data_kpi, colWidths=[280, 200])
    t_kpi.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#FAFBF9')),
        ('TEXTCOLOR', (0, 0), (1, 0), colors.HexColor('#495430')),
        ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#ECEFEA')),
    ]))
    story.append(t_kpi)
    story.append(Spacer(1, 20))
    
    story.append(Paragraph("Observations du Moteur d'Audit", style_section))
    for obs in analyse['observations']:
        story.append(Paragraph(f"- {obs}", style_texte))
    story.append(Spacer(1, 15))
    
    story.append(Paragraph("Plan de Route & Actions Recommandées", style_section))
    data_recom = [["Niveau de Priorité", "Action corrective requise"]]
    for r in analyse['recommandations']:
        data_recom.append([r['priorite'], r['action']])
        
    t_recom = Table(data_recom, colWidths=[120, 360])
    t_recom.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#5E6D3E')),
        ('TEXTCOLOR', (0, 0), (1, 0), colors.white),
        ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E6E1')),
    ]))
    story.append(t_recom)
    
    doc.build(story)
    buffer.seek(0)
    return buffer

def page_statistiques(request):
    profil_actif = get_profil_actif(request.user)
    if not request.user.is_authenticated:
        return redirect('/connexion/')
        
    tous_les_produits = Produit.objects.exclude(emplacement="Archivé")
    total_produits_base = tous_les_produits.count()
    pas_de_mouvements = True if total_produits_base == 0 else False
    
    view_mode = request.GET.get('view_mode', 'hebdomadaire')
    target_month_str = request.GET.get('target_month', '')
    target_year_str = request.GET.get('target_year', '2026')
    
    liste_mois = [
        {'valeur': '01', 'nom': 'Janvier'}, {'valeur': '02', 'nom': 'Février'},
        {'valeur': '03', 'nom': 'Mars'}, {'valeur': '04', 'nom': 'Avril'},
        {'valeur': '05', 'nom': 'Mai'}, {'valeur': '06', 'nom': 'Juin'},
        {'valeur': '07', 'nom': 'Juillet'}, {'valeur': '08', 'nom': 'Août'},
        {'valeur': '09', 'nom': 'Septembre'}, {'valeur': '10', 'nom': 'Octobre'},
        {'valeur': '11', 'nom': 'Novembre'}, {'valeur': '12', 'nom': 'Décembre'},
    ]
         
    annee_courante = date.today().year
    liste_annees = [str(a) for a in range(2026, max(annee_courante + 2, 2027))]
    
    if target_month_str and len(target_month_str) == 2:
        target_month_str = f"{target_year_str}-{target_month_str}-01"
    elif not target_month_str:
        target_month_str = date.today().strftime('%Y-%m-%d')
        target_year_str = str(date.today().year) 
            
    try:
        parsed_date = datetime.strptime(target_month_str, '%Y-%m-%d').date()
    except ValueError:
        parsed_date = date.today()
    
    mois_selectionne = str(parsed_date.month).zfill(2)
    annee_selectionnee = str(parsed_date.year)
    
    analyse = executer_moteur_analyse(int(annee_selectionnee), int(mois_selectionne))
    
    mouvements_periode = MouvementStock.objects.filter(
        date_mouvement__year=parsed_date.year,
        date_mouvement__month=parsed_date.month
    )
    
    total_operations = mouvements_periode.filter(type_mouvement='SORTIE').count()
    
    data_entrees = mouvements_periode.filter(type_mouvement='ENTREE').aggregate(total=Sum('quantite'))
    total_entrees = data_entrees['total'] if data_entrees['total'] is not None else 0
    
    data_sorties = mouvements_periode.filter(type_mouvement='SORTIE').aggregate(total=Sum('quantite'))
    total_sorties = data_sorties['total'] if data_sorties['total'] is not None else 0
            
    stock_total_actuel = Produit.objects.aggregate(total=Sum('quantite'))['total'] or 0
    taux_rotation = round((total_sorties / stock_total_actuel) * 100, 1) if stock_total_actuel > 0 else 0
    
    if view_mode == 'mensuel':
        chart_labels = ['Semaine 1', 'Semaine 2', 'Semaine 3', 'Semaine 4+']
        chart_sorties = [0, 0, 0, 0]  
        chart_operations = [0, 0, 0, 0]
        for m in mouvements_periode.filter(type_mouvement='SORTIE'):
            jour = m.date_mouvement.day
            idx = 0 if jour <= 7 else 1 if jour <= 14 else 2 if jour <= 21 else 3
            chart_sorties[idx] += m.quantite
            chart_operations[idx] += 1
    else:
        chart_labels = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']
        chart_sorties = [0, 0, 0, 0, 0, 0, 0]
        chart_operations = [0, 0, 0, 0, 0, 0, 0]
        debut_semaine = parsed_date - timedelta(days=parsed_date.weekday())
        mouvements_semaine = mouvements_periode.filter(
            type_mouvement='SORTIE',
            date_mouvement__gte=debut_semaine,
            date_mouvement__lte=debut_semaine + timedelta(days=6)
        )
        for m in mouvements_semaine:
            idx = m.date_mouvement.weekday()
            chart_sorties[idx] += m.quantite
            chart_operations[idx] += 1
          
    services_query = mouvements_periode.filter(type_mouvement='SORTIE').values('service').annotate(total=Sum('quantite')).order_by('-total')
    service_labels = [item['service'] for item in services_query] or ['Aucun service']
    service_data = [item['total'] for item in services_query] or [0]
        
    categories_uniques = Produit.objects.exclude(categorie__contains="=").values_list('categorie', flat=True).distinct()
    category_labels, category_data = [], []
    for cat in categories_uniques:
        if not cat or cat.strip() == "": continue
        
        total_cat = mouvements_periode.filter(type_mouvement='SORTIE', produit__categorie=cat).aggregate(total=Sum('quantite'))['total']
        if total_cat is None:
            noms_objets = Produit.objects.filter(categorie=cat).values_list('objet', flat=True)
            total_cat = mouvements_periode.filter(type_mouvement='SORTIE', objet__in=noms_objets).aggregate(total=Sum('quantite'))['total'] or 0
            
        if total_cat > 0:
            category_labels.append(cat)
            category_data.append(total_cat)
            
    if not category_labels:
        category_labels, category_data = ['Aucune activité'], [0]
    
    produits_perf = mouvements_periode.filter(type_mouvement='SORTIE').values('objet').annotate(total_sorti=Sum('quantite'))
    top_produits = produits_perf.order_by('-total_sorti')[:3]
    flop_produits = produits_perf.order_by('total_sorti')[:3]
    if produits_perf.exists(): pas_de_mouvements = False
    
    seuil_dormant = timezone.now() - timedelta(days=180)
    produits_dormants = Produit.objects.filter(derniere_activite__lte=seuil_dormant).order_by('derniere_activite')
    
    if request.method == "POST" and request.POST.get('type_analyse'):
        label_mapping = {
            'mensuel': "Audit Mensuel Spécifique", 'annuel': "Bilan Annuel Spécifique",
            'comparaison_mois': "Comparaison Évolution Mensuelle", 'comparaison_ans': "Comparaison Interannuelle Stratégique"
        }
        cle = request.POST.get('type_analyse')
        titre = label_mapping.get(cle, "Rapport Stratégique")
        annee_pdf = request.POST.get('periode_annee', annee_selectionnee)
        mois_pdf = request.POST.get('periode_mois', mois_selectionne)
        nom_mois = next((m['nom'] for m in liste_mois if m['valeur'] == mois_pdf), "")
        
        analyse_pdf = executer_moteur_analyse(int(annee_pdf), int(mois_pdf))
        pdf_buffer = generer_pdf_rapport(titre, analyse_pdf, annee_pdf, nom_mois)
        response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Rapport_{cle}_{annee_pdf}_{mois_pdf}.pdf"'
        return response
          
    return render(request, 'statistiques.html', {
        'profil_actif': profil_actif, 'total_operations': total_operations,
        'total_entrees': total_entrees, 'total_sorties': total_sorties,
        'taux_rotation': taux_rotation, 'pas_de_donnees_mouvement': pas_de_mouvements,
        'top_produits': top_produits, 'flop_produits': flop_produits,
        'chart_labels': chart_labels, 'chart_sorties': chart_sorties,
        'chart_operations': chart_operations, 'service_labels': service_labels,
        'service_data': service_data, 'category_labels': category_labels,
        'category_data': category_data, 'produits_dormants': produits_dormants,  
        'view_mode': view_mode, 'liste_mois': liste_mois,
        'liste_annees': liste_annees, 'mois_selectionne': mois_selectionne, 
        'annee_selectionnee': annee_selectionnee
    })
            
def page_gestion_utilisateurs(request):
    profil_actif = get_profil_actif(request.user)
    if not request.user.is_authenticated:
        return redirect('/connexion/')
            
    # CORRECTIF : Utilisation du nom d'accès inverse natif 'profilutilisateur' lié à ton modèle
    tous_les_comptes = User.objects.select_related('profilutilisateur').all()
    liste_utilisateurs = []
            
    for u in tous_les_comptes:
        if hasattr(u, 'profilutilisateur') and u.profilutilisateur is not None:   
            liste_utilisateurs.append({
                'id': u.id,
                'name': u.profilutilisateur.nom_complet,
                'username': u.username,
                'email': u.email,
                'clear_password': u.profilutilisateur.mot_de_passe_clair,
                'acces_inventaire': u.profilutilisateur.acces_inventaire,
                'acces_stocks': u.profilutilisateur.acces_stocks,
                'acces_historique': u.profilutilisateur.acces_historique,
                'acces_statistiques': u.profilutilisateur.acces_statistiques,
                'acces_gestion_utilisateurs': u.profilutilisateur.acces_gestion_utilisateurs,
                'acces_factures': u.profilutilisateur.acces_factures,
            })
        
    if request.method == "POST":  
        action_type = request.POST.get('action_type')    
        name = request.POST.get('name')
        username = request.POST.get('username')
        password = request.POST.get('password')
        email = request.POST.get('email', '')

        inv = request.POST.get('acces_inventaire') in ['true', 'on']
        stk = request.POST.get('acces_stocks') in ['true', 'on']
        hist = request.POST.get('acces_historique') in ['true', 'on']
        dem = request.POST.get('acces_gestion_demandes') in ['true', 'on']
        stat = request.POST.get('acces_statistiques') in ['true', 'on']
        uti = request.POST.get('acces_gestion_utilisateurs') in ['true', 'on']
        fac = request.POST.get('acces_factures') in ['true', 'on']
    
        if action_type == "creation":
            if name and username and password:
                username_lower = username.lower()
        
                if username_lower == "services":
                    inv = True
                    stk = True
                    hist = False
                    dem = True
                    stat = False 
                    uti = False
                    fac = False
                
                if not User.objects.filter(username=username_lower).exists():
                    nouvel_user = User.objects.create_user(
                        username=username_lower,
                        password=password,
                        email=email
                    )
                    nouvel_user.is_staff = True
                    nouvel_user.save()
        
                    ProfilUtilisateur.objects.create(
                        user=nouvel_user,
                        nom_complet=name,
                        mot_de_passe_clair=password,
                        acces_inventaire=inv,
                        accessible_stocks=stk, # s'assure de matcher l'attribut du modèle si requis
                        acces_stocks=stk,
                        acces_historique=hist,
                        acces_gestion_demandes=dem,
                        acces_statistiques=stat,
                        acces_gestion_utilisateurs=uti,
                        acces_factures=fac
                    )
        
        elif action_type == "modification":   
            user_id = request.POST.get('user_id')
            try:
                user_a_modifier = User.objects.get(id=user_id)
                    
                if user_a_modifier.is_superuser:
                    return redirect('/gestion-utilisateurs/')
                    
                username_lower = username.lower()
                
                if username_lower == "services":
                    inv = True
                    stk = True
                    hist = False   
                    dem = True
                    stat = False
                    uti = False
                    fac = False
                    
                user_a_modifier.username = username_lower
                user_a_modifier.email = email
                user_a_modifier.is_staff = True
                if password:
                    user_a_modifier.set_password(password)
                        
                user_a_modifier.save()   
                        
                # CORRECTIF : Remplacement de .profil par .profilutilisateur
                profil = user_a_modifier.profilutilisateur
                profil.nom_complet = name
        
                if password:
                    profil.mot_de_passe_clair = password
            
                profil.acces_inventaire = inv
                profil.acces_stocks = stk
                profil.acces_historique = hist  
                profil.acces_gestion_demandes = dem
                profil.acces_statistiques = stat
                profil.acces_gestion_utilisateurs = uti
                profil.acces_factures = fac
                profil.save()
                
            except User.DoesNotExist:
                pass
                    
        elif action_type == "suppression":
            user_id = request.POST.get('user_id')
            try:
                user_a_supprimer = User.objects.get(id=user_id)
                if not user_a_supprimer.is_superuser:
                    user_a_supprimer.delete()
            except User.DoesNotExist:
                pass    
                
        return redirect('/gestion-utilisateurs/')
                        
    return render(request, 'gestion_utilisateurs.html', {
        'profil_actif': profil_actif,
        'tous_les_utilisateurs': liste_utilisateurs
    })
        
def page_gestion_demandes(request):
    if not request.user.is_authenticated or not request.user.is_superuser:
        return redirect('/accueil/')
                
    profil_actif = get_profil_actif(request.user)
    if request.method == "POST":
        action = request.POST.get('action')
        demande_id = request.POST.get('demande_id')
                
        try:        
            demande = DemandeService.objects.get(id=demande_id)
            
            if action == "marquer_vu":
                if demande.statut == "en_attente":
                    demande.statut = "lu"
                    demande.save()
                return JsonResponse({"status": "success"})
                
            elif action == "valider":
                demande.statut = "valide"
                demande.save()
                return redirect('/gestion-demandes/')
        
            elif action == "refuser":
                demande.statut = "en_attente"
                demande.save()
                return redirect('/gestion-demandes/')
    
            elif action == "repondre":
                message_reponse = request.POST.get('message_reponse')
                demande.reponse_admin = message_reponse
                demande.save()
                return redirect('/gestion-demandes/')
    
        except DemandeService.DoesNotExist:
            pass
                
    search_query = request.GET.get('q', '')
            
    demandes_toutes = DemandeService.objects.all().order_by('-id')
                
    if search_query:
        demandes_toutes = demandes_toutes.filter(
            Q(message__icontains=search_query) | Q(service__icontains=search_query)
        )
                
    demandes_en_cours = [d for d in demandes_toutes if d.statut in ['en_attente', 'lu']]
    demandes_passees = [d for d in demandes_toutes if d.statut == 'valide']
            
    return render(request, 'gestion_demandes.html', {
        'profil_actif': profil_actif,
        'demandes_en_cours': demandes_en_cours,
        'demandes_passees': demandes_passees,
        'search_query': search_query  
    })
                
def page_factures(request):   
    if not request.user.is_authenticated or not request.user.is_superuser:
        return redirect('/accueil/')
        
    profil_actif = get_profil_actif(request.user)
                    
    if request.method == "POST":
        date_cmd = request.POST.get('date_commande')
        montant = request.POST.get('montant_total')
        fichier = request.FILES.get('fichier_facture')
                
        if date_cmd and montant and fichier:
            Facture.objects.create(
                date_commande=date_cmd,
                montant_total=montant,
                fichier_facture=fichier
            )   
            return redirect('/factures/')
    
    toutes_les_factures = Facture.objects.all().order_by('-date_commande') 
            
    return render(request, 'factures.html', {
        'profil_actif': profil_actif,
        'factures': toutes_les_factures
    })

def page_profil(request):
    if not request.user.is_authenticated:
        return redirect('/connexion/')
        
    profil_actif = get_profil_actif(request.user)
    succes = False
    
    if request.method == "POST":
        nouveau_password = request.POST.get('profil_password')
        uel_email = request.POST.get('profil_email')
        
        request.user.email = uel_email
        
        if nouveau_password:
            request.user.set_password(nouveau_password)
            
        request.user.save()
        
        # CORRECTIF : Remplacement de .profil par .profilutilisateur
        if not request.user.is_superuser and hasattr(request.user, 'profilutilisateur'):
            profil = request.user.profilutilisateur
            if nouveau_password:
                profil.mot_de_passe_clair = nouveau_password
            profil.save()
            
        if nouveau_password:
            login(request, request.user)
            
        succes = True

    return render(request, 'mon_profil.html', {
        'profil_actif': profil_actif,
        'succes': succes
    })

def page_deconnexion(request):
    logout(request)
    return redirect('/connexion/')

def modifier_mouvement(request, movimiento_id):
    mouvement = get_object_or_404(MouvementStock, id=movimiento_id)
    tous_les_produits = Produit.objects.all().order_by('objet')
    
    if request.method == 'POST':
        produit_id = request.POST.get('produit_id')
        if produit_id:
            produit_choisi = get_object_or_404(Produit, id=produit_id)
            mouvement.produit = produit_choisi
            mouvement.objet = produit_choisi.objet
            mouvement.reference = produit_choisi.reference
        
        mouvement.quantite = int(request.POST.get('quantite', mouvement.quantite))
        mouvement.service = request.POST.get('service', mouvement.service)
        mouvement.date_mouvement = request.POST.get('date_mouvement', mouvement.date_mouvement)
        
        mouvement.save()
        messages.success(request, "Le mouvement a été modifié avec succès.")
        return redirect('/historique/')
        
    return render(request, 'modifier_mouvement.html', {
        'mouvement': mouvement,
        'produits': tous_les_produits
    })
