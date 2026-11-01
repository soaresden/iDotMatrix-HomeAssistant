# Pixel Studio pour Android

Le **Pixel Studio** de Home Assistant et du PC, dans une appli Android : le téléphone pilote le cadre
iDotMatrix par Bluetooth, **sans Home Assistant ni PC**. Mêmes onglets, mêmes routines, même **Météo**
(un onglet du Studio, comme sur le Pi).

- Images et GIF ajoutés depuis le téléphone, routines qui les font défiler, planning, file d'envoi.
- **Météo** : l'heure, la météo d'[Open-Meteo](https://open-meteo.com) (gratuit, sans clé, il faut Internet),
  les écrans à remplir (Saint du jour, Agenda, Anniversaires, Compte à rebours, Notes, Mot du jour…), réglés
  sur l'aperçu comme dans le Studio.
- L'agenda propose les **agendas du téléphone** et les **anniversaires des contacts**, avec les autres.
- **Partager → Pixel Studio** depuis Keep (ou n'importe quelle appli) ajoute une note à la vue Météo affichée.
- Le Studio tourne en arrière-plan, appli fermée et écran du téléphone éteint : une notification
  « Pixel Studio » dit ce que montre le cadre, avec un bouton **Éteindre l'écran** / **Allumer l'écran**.
- Il repart tout seul au démarrage du téléphone et se reconnecte au cadre s'il s'éloigne.

Pas sur le téléphone : la conversion de vidéos (pas de ffmpeg) et la boutique.

## Installer

1. Copie `PixelStudio.apk` sur le téléphone (Android 7 ou plus récent) et ouvre-le.
2. Android demande d'autoriser l'installation depuis cette source (navigateur, gestionnaire de fichiers) :
   accepte. L'appli n'est pas sur le Play Store ; elle est signée avec une clé de développement.
   Play Protect peut prévenir que l'appli est inconnue : **Installer quand même**.
3. Ouvre **Pixel Studio**, accepte le Bluetooth (appareils à proximité), les notifications, l'agenda et les
   contacts, et de ne pas limiter la batterie (sinon Android endort les routines).

Pixel Studio s'installe par-dessus **Pixel Météo** : le cadre et la vue météo réglés sont repris tout seuls
(une routine « Météo », lancée sur le cadre).

## Utiliser

1. Allume le cadre et **ferme l'appli iDotMatrix** du téléphone (le cadre n'accepte qu'un téléphone à la fois).
2. En haut, **Chercher** les cadres, choisis le tien et sa taille, **Connecter**.
3. Le reste comme dans le Studio : onglet **Météo** pour une vue météo, routines, planning.

## Pour les développeurs

- `app/src/main/python/studio_android.py` : le serveur du Studio du PC (`desktop/pixel_studio.py`) et les
  modules de l'intégration (`idmcore`), **sans les modifier** (copiés à la compilation), sur 127.0.0.1.
- `app/src/main/python/bleak/` + `Ble.kt` + `Frame.kt` : bleak pour le client de l'intégration, par le
  Bluetooth d'Android.
- `app/src/main/python/phone.py` + `Phone.kt` + `Calendars.kt` : les agendas et anniversaires du téléphone,
  vus comme des agendas Home Assistant.
- `StudioService.kt` : le service au premier plan qui fait tourner le serveur, et sa notification.
- `MainActivity.kt` : la page du Studio (WebView).

Compiler (Linux ou WSL, avec le SDK Android, Gradle 8.10 et Python 3.13 pour Chaquopy) :

```bash
bash android/build_apk.sh
```

Le fichier sort dans `android/dist/PixelStudio.apk`.
