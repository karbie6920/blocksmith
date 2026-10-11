#!/usr/bin/env python3
"""
Interface languages of BlockSmith: Polish (source) and English.

Texts in the code are written in Polish and go through T("..."). When English is selected,
T returns the translation from the EN table, or the Polish text if there is none.

    import i18n
    i18n.set_language("en")
"""

LANGUAGES = {"pl": "Polski", "en": "English"}
_lang = "pl"


def set_language(code):
    global _lang
    _lang = code if code in LANGUAGES else "pl"


def language():
    return _lang


def T(text):
    """Text in the current language. Templates with {0}, {1} are translated before .format() is called."""
    if _lang == "en":
        return EN.get(text, text)
    return text


def count(n, kind):
    """Number with a noun: count(2, "klocek") -> "2 klocki" or "2 blocks"."""
    one, few, many, en_one, en_many = _NOUNS[kind]
    if _lang == "en":
        return f"{n} {en_one if n == 1 else en_many}"
    if n == 1:
        return f"1 {one}"
    return f"{n} {few}" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else f"{n} {many}"


_NOUNS = {
    "klocek": ("klocek", "klocki", "klocków", "block", "blocks"),
    "kostka": ("kostka", "kostki", "kostek", "cube", "cubes"),
}

COLORS = {
    "pl": {"czerwony": "czerwony", "zolty": "żółty", "zielony": "zielony", "niebieski": "niebieski", "fioletowy": "fioletowy"},
    "en": {"czerwony": "red", "zolty": "yellow", "zielony": "green", "niebieski": "blue", "fioletowy": "purple"},
}


class ColorNames(dict):
    """Dictionary of colour names in the current language. Keys are the internal names (czerwony, zolty...)."""

    def __getitem__(self, key):
        return COLORS[_lang].get(key, key)

    def get(self, key, default=None):
        return COLORS[_lang].get(key, key if default is None else default)


EN = {
    # ---------------------------------------------------------------- main window
    "BlockSmith  ·  wersja {0}": "BlockSmith  ·  version {0}",
    "Język": "Language",
    "Zmiana języka jest możliwa, gdy robot stoi i nie trwa budowa.": "The language can be changed when the robot is idle and no build is running.",
    "Pozycja: —": "Position: —",
    "Pozycja: X {:.1f}  Y {:.1f}  Z {:.1f} mm": "Position: X {:.1f}  Y {:.1f}  Z {:.1f} mm",
    "Robot: wyłączony": "Robot: off",
    "Kamera: wyłączona": "Camera: off",
    "Robot: ": "Robot: ",
    "Kamera: ": "Camera: ",
    "wyłączony": "off",
    "wyłączona": "off",
    "działa": "running",
    " (uruchomiony poza programem)": " (started outside the app)",
    "uruchamia się…": "starting…",
    "nie odpowiada": "not responding",
    "błąd, zobacz dziennik": "error, see the log",
    "Start": "Start",
    "Pole": "Area",
    "Kolory": "Colours",
    "Kalibracja": "Calibration",
    "Praca": "Work",
    "Budowa": "Build",
    "Robot wykonuje jeszcze poprzedni ruch.": "The robot is still carrying out the previous move.",
    "Nie udalo sie zapisac ustawien:": "Could not save settings:",
    "Brak środowiska ROS albo pliku dobot_web.py ({0}).\nUruchom program przez:  bash ~/dobot_web/dobot-app.sh":
        "ROS environment or dobot_web.py not found ({0}).\nStart the app with:  bash ~/dobot_web/dobot-app.sh",
    "Brak obrazu z kamery.\nUruchom sterownik kamery w zakładce Start.": "No camera image.\nStart the camera driver on the Start tab.",
    # ---------------------------------------------------------------- drivers
    "robot": "robot",
    "kamera": "camera",
    "[{0}] uruchamiam…": "[{0}] starting…",
    "[{0}] zatrzymuję…": "[{0}] stopping…",
    "[{0}] zatrzymany.": "[{0}] stopped.",
    "[{0}] zakończył się sam (kod {1}).": "[{0}] exited on its own (code {1}).",
    "[{0}] Nie udało się uruchomić: {1}": "[{0}] Could not start: {1}",
    "[kamera] adres w ustawieniach: „{0}”": "[camera] address in settings: “{0}”",
    "[kamera] bez adresu: łączę z pierwszą znalezioną kamerą": "[camera] no address: connecting to the first camera found",
    # ---------------------------------------------------------------- Start tab
    "Sterownik robota": "Robot driver",
    "Sterownik kamery": "Camera driver",
    "Uruchom": "Start",
    "Zatrzymaj": "Stop",
    "Bazowanie": "Homing",
    "Bazowanie…": "Homing…",
    "Pozycja domowa": "Home position",
    "Przyssawka": "Suction",
    "Przyssawka: ": "Suction: ",
    "wł.": "on",
    "wył.": "off",
    "Adres kamery": "Camera address",
    "puste = pierwsza znaleziona kamera": "empty = first camera found",
    "Uruchamiaj oba sterowniki automatycznie przy starcie programu": "Start both drivers automatically when the app opens",
    "Sterownik robota startuje około 20 sekund. Po włączeniu robota wykonaj bazowanie, przy pustej przestrzeni wokół ramienia. Zamknięcie programu zatrzymuje oba sterowniki.":
        "The robot driver takes about 20 seconds to start. After powering the robot on, run homing with the space around the arm clear. Closing the app stops both drivers.",
    "Sterownik robota już działa, uruchomiony poza programem (np. w terminalu). Nie uruchamiam drugiego.":
        "The robot driver is already running, started outside the app (e.g. in a terminal). Not starting a second one.",
    "Sterownik kamery już działa, uruchomiony poza programem (np. w terminalu). Nie uruchamiam drugiego.":
        "The camera driver is already running, started outside the app (e.g. in a terminal). Not starting a second one.",
    "Adres kamery zapisany. Zadziała po ponownym uruchomieniu sterownika kamery.": "Camera address saved. It takes effect after the camera driver is restarted.",
    "Adres kamery usunięty: sterownik połączy się z pierwszą kamerą, jaką znajdzie.": "Camera address cleared: the driver will connect to the first camera it finds.",
    "Bazowanie obraca ramię w pełnym zakresie.\nCzy przestrzeń wokół robota jest pusta?": "Homing swings the arm through its full range.\nIs the space around the robot clear?",
    # ---------------------------------------------------------------- Area tab
    "Pole robocze to obszar stołu, w którym program szuka klocków. Wszystko poza nim jest ignorowane.\n\nKliknij „Zaznacz pole”, a potem cztery rogi pola na obrazie, w dowolnej kolejności.":
        "The work area is the part of the table where the app looks for blocks. Everything outside it is ignored.\n\nClick “Mark area”, then click the four corners of the area on the image, in any order.",
    "Zaznacz pole": "Mark area",
    "Usuń pole": "Remove area",
    "Zaznaczanie… (kliknij rogi na obrazie)": "Marking… (click the corners on the image)",
    "Pole jest ustawione.": "The area is set.",
    "Pole nie jest ustawione: program analizuje cały kadr.": "The area is not set: the app analyses the whole frame.",
    "Brak obrazu z kamery. Uruchom sterownik kamery w zakładce Start.": "No camera image. Start the camera driver on the Start tab.",
    "Kliknij pierwszy róg pola roboczego na obrazie.": "Click the first corner of the work area on the image.",
    "Kliknij róg {0} z 4.": "Click corner {0} of 4.",
    "Usunięto pole robocze. Program analizuje cały kadr.": "Work area removed. The app analyses the whole frame.",
    "Pole robocze zapisane.": "Work area saved.",
    # ---------------------------------------------------------------- Colours tab
    "Połóż w polu roboczym JEDEN klocek i kliknij „Naucz” przy jego kolorze. Program szuka tylko nauczonych kolorów.":
        "Put ONE block in the work area and click “Teach” next to its colour. The app only looks for colours it has been taught.",
    "Naucz": "Teach",
    "Usuń": "Remove",
    "   (odcień {0})": "   (hue {0})",
    "   nie nauczony": "   not taught",
    "Próg nasycenia": "Saturation threshold",
    "Wyżej: mniej fałszywych wykryć. Niżej: łapie bledsze kolory.": "Higher: fewer false detections. Lower: picks up paler colours.",
    "Pokaż, co program uznaje za kolorowe": "Show what the app treats as coloured",
    "Brak obrazu z kamery.": "No camera image.",
    "Nie widzę klocka w polu roboczym. Połóż jeden i spróbuj ponownie.": "I can't see a block in the work area. Place one and try again.",
    "Nauczono: {0} (odcień {1}, nasycenie {2}).": "Learned: {0} (hue {1}, saturation {2}).",
    " Uwaga: bardzo blisko koloru {0}, będą się mylić.": " Warning: very close to {0}, they will be confused.",
    "  ·  odcień {0}": "  ·  hue {0}",
    # ---------------------------------------------------------------- Calibration tab
    "Powtórz dla 4 miejsc blisko rogów pola, najlepiej dodaj piąte na środku.\nA. Połóż jeden klocek tak, żeby ramię go nie zasłaniało, i kliknij przycisk 1.\nB. Ustaw przyssawkę na środku klocka: ręką z wciśniętym Unlock albo przyciskami.\nC. Kliknij przycisk 2.":
        "Repeat for 4 spots near the corners of the area, ideally add a fifth in the middle.\nA. Place one block so the arm does not cover it and click button 1.\nB. Put the suction cup on the centre of the block: by hand with Unlock pressed, or with the buttons.\nC. Click button 2.",
    "1. Zapamiętaj klocek": "1. Remember block",
    "2. Zapisz pozycję robota": "2. Save robot position",
    "Krok": "Step",
    "X −  tył": "X −  back",
    "X +  przód": "X +  forward",
    "Y −  prawo": "Y −  right",
    "Y +  lewo": "Y +  left",
    "Z −  dół": "Z −  down",
    "Z +  góra": "Z +  up",
    "Usuń ostatni punkt": "Remove last point",
    "Wyczyść kalibrację": "Clear calibration",
    "Sprawdź: najedź nad klocek": "Check: move above the block",
    "Zasięg robota": "Robot reach",
    "Od": "From",
    "do": "to",
    "od osi podstawy": "from the base axis",
    "Pokaż zasięg na obrazie (zielony pierścień)": "Show reach on the image (green ring)",
    "Pierścień pojawia się po kalibracji. Jeśli sterownik odrzuca ruchy przy krawędzi, zmniejsz górną granicę.":
        "The ring appears after calibration. If the driver rejects moves near the edge, lower the upper limit.",
    "Miejsce odkładania": "Drop-off point",
    "Połóż klocek tam, gdzie robot ma odkładać (poza polem roboczym), ustaw na nim przyssawkę i kliknij.":
        "Place a block where the robot should drop blocks (outside the work area), put the suction cup on it and click.",
    "Zapisz miejsce odkładania": "Save drop-off point",
    "Puść klocek z wysokości": "Release the block from",
    "Potrzeba co najmniej 4 punktów (jest {0}).": "At least 4 points are needed (there are {0}).",
    "Punkty leżą zbyt blisko siebie albo w jednej linii. Rozstaw je w rogach pola.": "The points are too close together or in one line. Spread them out to the corners of the area.",
    "Nie udało się wyliczyć kalibracji z tych punktów.": "Could not compute the calibration from these points.",
    "Punkty: {0}. {1}": "Points: {0}. {1}",
    "Kalibracja gotowa z 4 punktów. Przy 4 punktach nie da się policzyć błędu: dodaj piąty punkt albo użyj przycisku „Sprawdź”.":
        "Calibration ready from 4 points. With 4 points the error cannot be computed: add a fifth point or use the “Check” button.",
    "Kalibracja gotowa z {0} punktów. Średni błąd dopasowania: {1:.1f} mm.": "Calibration ready from {0} points. Mean fit error: {1:.1f} mm.",
    " To dużo: któryś punkt jest niedokładny. Wyczyść i powtórz.": " That is a lot: one of the points is inaccurate. Clear and repeat.",
    "\nWysokość chwytu: Z = {0:.1f} mm.": "\nPick height: Z = {0:.1f} mm.",
    "Zapisane: X {0:.0f}, Y {1:.0f}, Z {2:.0f} mm": "Saved: X {0:.0f}, Y {1:.0f}, Z {2:.0f} mm",
    "Nie ustawiono.": "Not set.",
    "Poczekaj, aż robot skończy ruch.": "Wait until the robot finishes moving.",
    "Najpierw naucz co najmniej jeden kolor w zakładce Kolory.": "First teach at least one colour on the Colours tab.",
    "W polu musi być widoczny dokładnie jeden klocek (widzę {0}). Sprawdź też, czy ramię go nie zasłania.":
        "Exactly one block must be visible in the area (I see {0}). Also check that the arm is not covering it.",
    "Położenie klocka zapamiętane. Teraz ustaw przyssawkę na środku klocka i kliknij „2. Zapisz pozycję robota”.":
        "Block position remembered. Now put the suction cup on the centre of the block and click “2. Save robot position”.",
    "Najpierw kliknij „1. Zapamiętaj klocek”.": "First click “1. Remember block”.",
    "Punkt {0} zapisany. Podnieś ramię, przełóż klocek w kolejne miejsce i powtórz.": "Point {0} saved. Lift the arm, move the block to the next spot and repeat.",
    "Sprawdzenie: najeżdżam 15 mm nad klocek ({0}).": "Check: moving 15 mm above the block ({0}).",
    "Miejsce odkładania zapisane.": "Drop-off point saved.",
    "tu ustaw przyssawkę": "put the suction cup here",
    "odkładanie": "drop-off",
    "oś robota": "robot axis",
    "zielone: zasięg robota {0}–{1} mm": "green: robot reach {0}–{1} mm",
    "Cały kadr jest poza zasięgiem robota": "The whole frame is outside the robot's reach",
    "Cały kadr jest w zasięgu robota": "The whole frame is within the robot's reach",
    # ---------------------------------------------------------------- Work tab
    "Robot podnosi klocek wybranego koloru i odkłada go w miejscu odkładania. Zielony pierścień to zasięg robota: klocki poza nim są pomijane.":
        "The robot picks up a block of the chosen colour and puts it at the drop-off point. The green ring is the robot's reach: blocks outside it are skipped.",
    "Zabierz jeden: {0}": "Pick one: {0}",
    "Zabierz wszystkie: {0}": "Pick all: {0}",
    "Zabierz wszystkie klocki": "Pick all blocks",
    "Prędkość": "Speed",
    "Widzę: {0}.": "I see: {0}.",
    "Brak nauczonych kolorów.": "No colours taught.",
    "\nRobot: {0}": "\nRobot: {0}",
    "ruch…": "moving…",
    "\nSortowanie w toku.": "\nSorting in progress.",
    "za blisko robota": "too close to the robot",
    "za daleko": "too far",
    "zła wysokość chwytu": "wrong pick height",
    "Najpierw wykonaj kalibrację (zakładka 4).": "First run the calibration (Calibration tab).",
    "Najpierw ustaw miejsce odkładania (zakładka 4).": "First set the drop-off point (Calibration tab).",
    "Robot nie odpowiada. Uruchom sterownik w zakładce Start.": "The robot is not responding. Start the driver on the Start tab.",
    "Nie widzę takiego klocka w polu.": "I can't see a block like that in the area.",
    "Klocek jest poza zasięgiem robota: ": "The block is outside the robot's reach: ",
    "Zabieram klocek: {0} z X {1:.0f}, Y {2:.0f}.": "Picking block: {0} from X {1:.0f}, Y {2:.0f}.",
    "Koniec: zabrano {0}.": "Done: picked {0}.",
    "Nie ma czego zabrać.": "Nothing to pick.",
    "Przerywam: ten sam klocek nie dał się podnieść trzy razy z rzędu. Sprawdź przyssawkę i wysokość chwytu.":
        "Stopping: the same block could not be picked three times in a row. Check the suction cup and the pick height.",
    "Przerywam po 40 klockach.": "Stopping after 40 blocks.",
    # ---------------------------------------------------------------- Build tab
    "Ollama proponuje budowle z kostek, które widzi kamera (najwyżej 6). Wybierz jedną, obejrzyj podgląd pod obrazem z kamery i kliknij „Buduj”. Kalibrację wykonaj na tych samych kostkach.":
        "Ollama proposes structures from the cubes the camera sees (6 at most). Pick one, look at the preview under the camera image and click “Build”. Calibrate with the same cubes you build with.",
    "Zapisz miejsce budowy": "Save build site",
    "Postaw kostkę tam, gdzie ma stanąć budowla (poza polem roboczym), ustaw na niej przyssawkę i kliknij.":
        "Place a cube where the structure should stand (outside the work area), put the suction cup on it and click.",
    "Kostka": "Cube",
    "Model": "Model",
    "Odśwież": "Refresh",
    "Życzenie dla Ollamy, np. „coś wysokiego” (można zostawić puste)": "A wish for Ollama, e.g. “something tall” (may be left empty)",
    "Zaproponuj budowle": "Propose structures",
    "Ollama myśli… to może potrwać minutę": "Ollama is thinking… this may take a minute",
    "Kostki do wzięcia: ": "Cubes available: ",
    "brak": "none",
    "Buduj": "Build",
    "Wznów": "Resume",
    "Przerwij budowę": "Abort build",
    "Korekta obrotu kostek": "Cube rotation correction",
    "Odwróć kierunek obrotu": "Reverse rotation direction",
    "Uwzględnij obrót podstawy robota": "Account for robot base rotation",
    "Zostaw wyłączone, jeśli kostki stają równo. Pierwsze włącz, gdy stają obrócone w złą stronę. Drugie, gdy skrzywienie zależy od tego, skąd kostka została wzięta.":
        "Leave both off if the cubes end up straight. Turn on the first if they end up rotated the wrong way. The second if the skew depends on where the cube was picked from.",
    "Miejsce budowy: X {0:.0f}, Y {1:.0f}, Z {2:.0f} mm.": "Build site: X {0:.0f}, Y {1:.0f}, Z {2:.0f} mm.",
    "Miejsce budowy nie jest ustawione. Postaw kostkę tam, gdzie ma stanąć budowla, ustaw na niej przyssawkę i kliknij „Zapisz miejsce budowy”.":
        "The build site is not set. Place a cube where the structure should stand, put the suction cup on it and click “Save build site”.",
    "Miejsce budowy zapisane. Zabierz z niego kostkę przed budową.": "Build site saved. Remove the cube from it before building.",
    "Ollama nie odpowiada": "Ollama is not responding",
    "Nie widzę w polu żadnej kostki w zasięgu robota.": "I can't see any cube in the area within the robot's reach.",
    "Ollama nie odpowiada albo nie ma żadnego modelu. Sprawdź: ollama list": "Ollama is not responding or has no model. Check: ollama list",
    "Nieoczekiwany błąd: {0}": "Unexpected error: {0}",
    "Budowla": "Structure",
    "Ollama": "Ollama",
    "wzorzec programu": "built-in template",
    " Pokazuję wzorce wbudowane w program.": " Showing the app's built-in templates.",
    "Żadna propozycja Ollamy nie nadawała się do zbudowania. Pokazuję wzorce wbudowane w program.": "None of Ollama's proposals could be built. Showing the app's built-in templates.",
    "Ollama zaproponowała budowle: {0}.": "Ollama proposed structures: {0}.",
    "{0}  ·  {1}, {2} poz.  ·  {3}": "{0}  ·  {1}, {2} lvl  ·  {3}",
    "Program poprawił plan: ": "The app corrected the plan: ",
    "plan nie zawierał kostek": "the plan contained no cubes",
    "usunięto kostki poza siatką lub zdublowane": "removed cubes outside the grid or duplicated",
    "dosunięto kostki wiszące w powietrzu": "moved floating cubes down",
    "przycięto do liczby dostępnych kostek: ": "trimmed to the number of available cubes: ",
    "zmieniono kolory na dostępne": "changed colours to available ones",
    "Wieża": "Tower",
    "Wszystkie kostki jedna na drugiej.": "All cubes stacked on top of each other.",
    "Schody": "Stairs",
    "Każdy kolejny słupek o jedną kostkę wyższy.": "Each next column is one cube taller.",
    "Mur": "Wall",
    "Dwa poziomy kostek obok siebie.": "Two levels of cubes side by side.",
    "Zamek": "Castle",
    "Kwadratowa podstawa z wieżyczką.": "A square base with a turret.",
    "Zaproponuj trzy budowle.": "Propose three structures.",
    "Model nie zwrócił propozycji w oczekiwanej postaci.": "The model did not return proposals in the expected form.",
    "Ollama zwróciła błąd {0}: {1}": "Ollama returned error {0}: {1}",
    "Brak połączenia z Ollamą ({0}). Sprawdź, czy działa: ollama list": "No connection to Ollama ({0}). Check that it is running: ollama list",
    "Tu pojawi się podgląd wybranej budowli.": "The preview of the selected structure will appear here.",
    "Przeciągnij, aby obrócić. Kreska z kropką wskazuje kierunek od robota.": "Drag to rotate. The line with a dot points away from the robot.",
    "Najpierw zapisz miejsce budowy.": "First save the build site.",
    "Kostka na poziomie {0} nie mieści się w zasięgu robota: {1}. Przesuń miejsce budowy.": "The cube on level {0} is outside the robot's reach: {1}. Move the build site.",
    "Budowla jest za wysoka dla robota w tym miejscu (potrzeba Z {0:.0f} mm, limit {1:.0f} mm).": "The structure is too tall for the robot at this spot (needs Z {0:.0f} mm, limit {1:.0f} mm).",
    "Zbudować „{0}” ({1})?\n\nMiejsce budowy musi być puste, a przestrzeń wokół robota wolna.": "Build “{0}” ({1})?\n\nThe build site must be empty and the space around the robot clear.",
    "Zaczynam budowę: {0}.": "Starting build: {0}.",
    " Kliknij „Wznów” albo „Przerwij budowę”.": " Click “Resume” or “Abort build”.",
    "Budowa przerwana.": "Build aborted.",
    "Zatrzymano. Sprawdź, czy robot nie trzyma kostki (przycisk Przyssawka w zakładce Start).": "Stopped. Check that the robot is not holding a cube (Suction button on the Start tab).",
    "Ruch się nie powiódł (szczegóły w dzienniku).": "The move failed (details in the log).",
    "Budowla „{0}” gotowa.": "Structure “{0}” is finished.",
    "Nie widzę wolnej kostki w kolorze {0}. Dołóż ją do pola.": "I can't see a free {0} cube. Add one to the area.",
    "Kostka {0} z {1}: {2}, poziom {3}.": "Cube {0} of {1}: {2}, level {3}.",
    "Nie udało się wysłać ruchu do robota.": "Could not send the move to the robot.",
    "Budowa „{0}”: postawiono {1} z {2}.": "Building “{0}”: placed {1} of {2}.",
    " Wstrzymana.": " Paused.",
    "budowa": "build site",
    # ---------------------------------------------------------------- robot motion (dobot_web.py)
    "punkt za blisko podstawy ({0:.0f} mm, minimum {1:.0f} mm)": "point too close to the base ({0:.0f} mm, minimum {1:.0f} mm)",
    "punkt poza zasięgiem ({0:.0f} mm, maksimum {1:.0f} mm)": "point out of reach ({0:.0f} mm, maximum {1:.0f} mm)",
    "Z={0:.0f} mm jest poniżej limitu {1:.0f} mm": "Z={0:.0f} mm is below the limit of {1:.0f} mm",
    "Z={0:.0f} mm jest powyżej limitu {1:.0f} mm": "Z={0:.0f} mm is above the limit of {1:.0f} mm",
    "pole „on” musi być true albo false": "field “on” must be true or false",
    "Lista akcji ma zły format.": "The action list has a bad format.",
    "Plan skrócony do {0} kroków.": "Plan shortened to {0} steps.",
    "krok nie jest obiektem": "step is not an object",
    "ruch bez współrzędnych": "move without coordinates",
    "przesunięcie o zero": "shift by zero",
    "przegub musi być z zakresu 1-4": "joint must be in the range 1-4",
    "nieznany typ akcji „{0}”": "unknown action type “{0}”",
    "wartość nie jest liczbą": "value is not a number",
    "Krok {0} pominięty: {1}": "Step {0} skipped: {1}",
    "Ruch do ": "Move to ",
    "Przesunięcie: ": "Shift: ",
    "Obrót przegubu J{0} o {1}": "Rotate joint J{0} by {1}",
    "włącz": "on",
    "wyłącz": "off",
    "Pauza {0:g} s": "Pause {0:g} s",
    "Powrót do pozycji domowej": "Return to home position",
    "Brak danych o pozycji. Sprawdź, czy sterownik Dobota jest uruchomiony.": "No position data. Check that the Dobot driver is running.",
    "Serwer ruchu /PTP_action nie odpowiada. Uruchom sterownik Dobota.": "The motion server /PTP_action is not responding. Start the Dobot driver.",
    "Ruch nie zakończył się w oczekiwanym czasie.": "The move did not finish in the expected time.",
    "Sterownik odrzucił cel (poza zasięgiem albo limitami przegubów).": "The driver rejected the target (out of reach or joint limits).",
    "[robot] Parametry sterownika wczytane ponownie: {0}": "[robot] Driver parameters reloaded: {0}",
    "[robot] Nie udało się wczytać parametrów sterownika: {0}. Uruchom sterownik ponownie.": "[robot] Could not load driver parameters: {0}. Restart the driver.",
    "Błąd akcji ruchu: ": "Motion action error: ",
    "Ruch przerwany.": "Move interrupted.",
    "Ruch nie powiódł się (status {0}).": "The move failed (status {0}).",
    "przyssawki": "suction",
    "bazowania": "homing",
    "Usługa {0} nie odpowiada. Uruchom sterownik Dobota.": "The {0} service is not responding. Start the Dobot driver.",
    "Usługa {0} nie odpowiedziała w czasie.": "The {0} service did not respond in time.",
    "Usługa {0}: {1}": "Service {0}: {1}",
    "Brak kroków do wykonania.": "No steps to execute.",
    "STOP: przerwano bieżącą sekwencję.": "STOP: current sequence interrupted.",
    "✗ Nieoczekiwany błąd: {0}": "✗ Unexpected error: {0}",
    "Brak danych o kątach przegubów.": "No joint angle data.",
    "Nieobsługiwana akcja: {0}": "Unsupported action: {0}",
    "Ollama nie odpowiada pod adresem ": "Ollama is not responding at ",
    ". Uruchom ją poleceniem „ollama serve”.": ". Start it with “ollama serve”.",
    "W Ollamie nie ma żadnego modelu. Pobierz go, np. „ollama pull qwen2.5:3b”.": "Ollama has no model. Pull one, e.g. “ollama pull qwen2.5:3b”.",
    "Brak połączenia z Ollamą: {0}": "No connection to Ollama: {0}",
    "Model nie zwrócił poprawnej odpowiedzi. Spróbuj sformułować polecenie inaczej.": "The model did not return a valid answer. Try phrasing the command differently.",
    "Puste polecenie.": "Empty command.",
    "Nieznana oś.": "Unknown axis.",
    "Wykonuję plan z polecenia.": "Executing the plan from the command.",
    "Nieznany adres.": "Unknown address.",
    "Błędne dane: {0}": "Bad data: {0}",
    "Błąd serwera: {0}": "Server error: {0}",
    "Konsola działa: http://{0}:{1}": "Console running: http://{0}:{1}",
}
