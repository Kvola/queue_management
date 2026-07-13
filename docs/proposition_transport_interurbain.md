# Proposition — Réservations d'une compagnie de transport inter-urbain 🚌

*Comment la plateforme « File d'attente » couvre le métier d'une compagnie
de cars inter-urbains (type Abidjan ↔ Bouaké ↔ Korhogo), ce qui marche tel
quel, et ce qu'il faudrait ajouter.*

## 1. La correspondance des concepts

Le cœur du produit — services à capacité limitée, créneaux horaires,
tickets nominatifs, check-in — est exactement la structure d'une
compagnie de transport :

| Concept transport | Concept plateforme | Commentaire |
|---|---|---|
| Compagnie | Société (établissement) | Isolation multi-compagnies native |
| Gare / agence de départ | **Site** (QR d'entrée, borne, écran) | Un QR par gare |
| Ligne / destination (« → Bouaké ») | **Service** | Préfixe = code ligne (BKE-001…) |
| Départ horaire (7h00, 9h30…) | **Créneau de rendez-vous** | Plages d'ouverture = grille horaire |
| Capacité du car (ex. 50 places) | **Capacité par créneau** | Complet = créneau grisé dans l'app |
| Réservation | **Ticket programmé** (RDV) | À distance depuis l'app, ou au guichet/borne |
| Embarquement | **Check-in** (« Je suis arrivé(e) ») | File d'embarquement priorisée |
| Guichet de vente | **Guichet** + « Ma console » | Agents connectés, appel des voyageurs |
| Tableau des départs en gare | **Écran d'affichage** | Numéros appelés à l'embarquement |
| No-show (voyageur absent au départ) | **Auto-absent** + cron RDV | Place libérable, voyageur notifié |

## 2. Le parcours voyageur, avec l'existant

1. **Réserver** : app → « Mes sites » (gare déjà visitée) ou scan du QR en
   gare → service « Abidjan → Bouaké » → **Prendre rendez-vous** → jour →
   départ 9h30 (23 places restantes) → réservation confirmée + notification.
2. **Le jour du départ** : le voyageur arrive en gare, ouvre sa
   réservation → **« Je suis arrivé(e) »** : il entre dans la file
   d'embarquement, l'agent l'appelle depuis sa console (contrôle du
   billet/bagages), l'écran de gare affiche les numéros appelés.
3. **Retardataires** : un réservé non enregistré passe automatiquement en
   Absent après le délai configuré ; l'agent peut le « Re-mettre en file »
   s'il arrive in extremis. Les sans-réservation prennent un ticket
   d'attente (borne ou app) et embarquent si des places restent.

**Réglages types** : durée de créneau = 1 min avec un créneau par horaire
de départ ? Non — plus simple : plages d'ouverture réduites à l'heure de
chaque départ (ex. 07:00–07:30 avec créneau de 30 min = LE départ de 7h),
capacité = places du car, quota RDV par client relevé (familles).

## 3. Ce qui manque pour un service commercial complet

Par ordre de valeur :

1. **Paiement** (le vrai manquant) : mobile money (Orange/MTN/Wave) à la
   réservation, sinon les no-shows coûtent cher. Extension naturelle :
   état « réservé non payé » → confirmation au paiement (webhook PSP),
   expiration automatique des impayés. *Chantier moyen.*
2. **Grille horaire par date** : aujourd'hui les plages sont hebdomadaires ;
   il faudrait des départs par date (renforts jours de fête, suppressions),
   soit un modèle « départ » daté généré depuis la grille. *Chantier moyen.*
3. **Sièges numérotés** (optionnel selon le positionnement — beaucoup de
   compagnies font l'embarquement libre) : plan de car + choix du siège.
   *Chantier conséquent.*
4. **Manifeste passagers** : la liste d'embarquement existe déjà de fait
   (tickets du créneau) — un rapport PDF par départ suffit. *Petit chantier.*
5. **Trajets retour / multi-tronçons** : hors périmètre v1 ; se modélise en
   deux réservations.

## 4. Recommandation

Un **module d'extension** `queue_transport` par-dessus la plateforme (sans
la modifier) : modèle « départ » (date + ligne + véhicule/capacité) qui
alimente les créneaux, paiement mobile money, manifeste PDF. La plateforme
actuelle permet déjà un **pilote sans paiement** (réservation + embarquement
+ statistiques de remplissage) sur une ligne, en une journée de
configuration — c'est le chemin que je recommande : valider l'usage en gare
avant d'investir dans le paiement.

*Document de proposition — 2026-07-12.*
