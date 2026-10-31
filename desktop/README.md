# Pixel Studio pour Windows

Pixel Studio, le studio de l'intégration iDotMatrix pour Home Assistant, dans un seul programme Windows :
il pilote ton cadre iDotMatrix directement par le Bluetooth du PC, **sans Home Assistant**.
Importer des images, GIF et vidéos courtes, les retoucher dans l'Atelier, les ranger dans une galerie
et les envoyer au cadre.

**[⬇ Télécharger PixelStudio.exe](https://github.com/soaresden/iDotMatrix-HomeAssistant/releases/latest/download/PixelStudio.exe)**
(23 Mo, rien d'autre à installer)

> Version d'essai : testée sur PC avec un cadre simulé, pas encore sur un vrai cadre.
> Si quelque chose coince, le journal du studio et la fenêtre noire disent ce qui s'est passé.

## Ce qu'il faut

- Windows 10 (version 1709 ou plus récente) ou Windows 11, 64 bits.
- Du Bluetooth 4.0 ou plus récent (« Bluetooth basse consommation », LE) : presque tous les portables l'ont ;
  un PC fixe sans Bluetooth a besoin d'une clé USB Bluetooth 4.0+.
- Un cadre iDotMatrix (nom Bluetooth `IDM-…`), 64×64, 32×32 ou 16×16.
- Pas besoin d'appairer le cadre dans les réglages Bluetooth de Windows.

## Démarrer

1. Télécharge `PixelStudio.exe` et mets-le où tu veux (Bureau, Documents…).
2. Allume le cadre et **ferme l'appli iDotMatrix du téléphone** : le cadre n'accepte qu'un seul appareil
   connecté à la fois. Active le Bluetooth du PC.
3. Double-clique sur `PixelStudio.exe`. Windows peut afficher « Windows a protégé votre ordinateur »
   (le programme n'est pas signé) : **Informations complémentaires**, puis **Exécuter quand même**.
4. Une fenêtre noire s'ouvre (c'est le programme : laisse-la ouverte, la fermer quitte Pixel Studio),
   puis le navigateur sur `http://127.0.0.1:8765`.
5. Dans la barre du haut : **Chercher les cadres**, choisis le tien et sa **taille**, puis **Connecter**.
   Le studio s'ouvre en dessous. **Tester** envoie un arc-en-ciel au cadre pour vérifier que tout marche.

La barre du haut montre l'état : point vert = connecté, rouge = pas connecté. **Déconnecter** libère le
cadre (pour reprendre l'appli du téléphone). Le cadre et sa taille sont retenus : au lancement suivant,
Pixel Studio s'y reconnecte tout seul.

Relancer `PixelStudio.exe` alors qu'il tourne déjà rouvre simplement la page.

## Où sont les fichiers

- La galerie (les GIF prêts pour le cadre) : `Documents\Pixel Studio\idotmatrix`.
- Les réglages, routines, collections et le journal : `%APPDATA%\Pixel Studio`.

## Ce qui change par rapport à Home Assistant

- Le PC doit rester allumé avec Pixel Studio ouvert pour que les routines et la programmation horaire
  continuent ; PC éteint, le cadre garde simplement le dernier GIF envoyé.
- Pas des affichages de l'intégration (horloge du cadre, bitcoin…) : le studio, la galerie et l'onglet **Météo**
  (l'heure avec les secondes, jusqu'à 4 villes qui se relaient, le nom de la ville, la couleur de l'heure,
  les 4 heures choisies ou le lever/coucher du soleil, la luminosité selon le soleil). On tape une ville :
  recherche et prévisions par Open-Meteo, gratuit, sans clé ; il faut Internet sur le PC, et le PC allumé avec
  Pixel Studio ouvert pour que l'heure avance.
- Pas d'onglet Store. Un seul cadre à la fois.
- Certains textes du studio parlent encore « du Pi » : c'est le PC ici.

## En cas de souci

- **« Aucun cadre trouvé »** : le cadre est-il allumé, près du PC, et l'appli du téléphone bien fermée ?
  Un cadre déjà connecté (au téléphone, à Home Assistant) n'apparaît pas dans la recherche.
- **« … ne répond pas »** : même chose ; éteins puis rallume le cadre, puis **Connecter**.
- **La page dit « Pixel Studio est fermé »** : la fenêtre noire a été fermée, relance `PixelStudio.exe`.
- Un antivirus peut se méfier d'un `.exe` non signé fabriqué avec PyInstaller : c'est un faux positif
  connu ; le code est dans ce dépôt (`desktop/`).

---

## Pour les développeurs

Le programme réutilise sans les modifier les modules de l'intégration (`studio.py`, `journal.py`,
`routines.py`, `schedule.py`, `media.py`, le panneau `www/idotmatrix-studio.js` et la bibliothèque
Bluetooth `client/`) :

- `desktop/pixel_studio.py` : serveur local (127.0.0.1 seulement) qui sert la page et répond aux
  commandes websocket du panneau avec les gestionnaires de `studio.py` ; refuse les requêtes venant
  d'une autre page web (en-tête `Origin`).
- `desktop/homeassistant/` : les quelques morceaux de Home Assistant que ces modules utilisent
  (bus d'événements, `Store`, minuteries, décorateurs websocket), chargés seulement par l'appli de bureau.
- `desktop/overrides/coordinator.py` : remplace le coordinateur de l'intégration (un cadre sur le
  Bluetooth du PC).
- `desktop/index.html` : la barre Bluetooth et l'objet `hass` minimal que le panneau attend
  (`callWS`, `connection.subscribeEvents`, `fetchWithAuth`).

Lancer depuis les sources (Python 3.12+ avec `bleak`, `bleak-retry-connector`, `pillow`, `cryptography`,
`voluptuous`, `aiohttp`) :

```bash
python desktop/pixel_studio.py
```

Fabriquer l'exe :

```bash
powershell -ExecutionPolicy Bypass -File tools/build_pixel_studio_exe.ps1
```

Tests (le serveur contre un cadre simulé) : `python -m pytest -q desktop/desktop_checks.py`.
