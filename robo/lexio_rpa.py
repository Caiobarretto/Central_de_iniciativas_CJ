# -*- coding: utf-8 -*-
"""RPA assistido para upload e envio de minutas Word na Lexio.

Fluxo esperado pela usuária:
- abre Lexio/Chrome visível;
- realiza login com e-mail/senha informados quando a tela aparecer;
- sobe cada documento Word individualmente;
- seleciona o tipo conforme o documento: Substabelecimento Outros (interno), Substabelecimento Cliente (externo) ou Procuração;
- marca que não está assinado;
- preenche ID GLPI como "A PREENCHER";
- adiciona os signatários recebidos da minuta/importação, preferencialmente por nome + e-mail;
- posiciona assinatura de forma assistida/automática no final do documento;
- envia para assinatura;
- retorna o link da página do contrato.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

DEFAULT_LOGIN_EMAIL = os.getenv("LEXIO_QCA_EMAIL", "")
DEFAULT_LOGIN_PASSWORD = os.getenv("LEXIO_QCA_PASSWORD", "")


def log(msg):
    print(str(msg), flush=True)


def norm_text(s):
    return re.sub(r"\s+", " ", str(s or "").strip())


def first_visible(page, selector, timeout=4000):
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=timeout)
    return loc


def click_selector(page, selector, timeout=5000):
    try:
        loc = first_visible(page, selector, timeout=timeout)
        loc.click(timeout=timeout)
        return True
    except Exception:
        return False


def click_by_text(page, texts, timeout=5000, exact=False):
    if isinstance(texts, str):
        texts = [texts]
    for text in texts:
        for method in ("get_by_text", "css"):
            try:
                if method == "get_by_text":
                    loc = page.get_by_text(text, exact=exact).first
                else:
                    safe = text.replace("'", "\\'")
                    loc = page.locator(f"button:has-text('{safe}'), a:has-text('{safe}'), [role=button]:has-text('{safe}'), div[role=option]:has-text('{safe}')").first
                loc.wait_for(state="visible", timeout=timeout)
                loc.click(timeout=timeout)
                return True
            except Exception:
                pass
    return False



def force_click(locator, timeout=6000):
    """Clica de forma mais tolerante em componentes React/Ark UI que às vezes interceptam o click normal."""
    try:
        locator.wait_for(state="visible", timeout=timeout)
        locator.scroll_into_view_if_needed(timeout=timeout)
        locator.click(timeout=timeout)
        return True
    except Exception:
        try:
            locator.evaluate("el => el.click()", timeout=timeout)
            return True
        except Exception:
            return False


def click_option_by_value_or_text(page, value=None, texts=None, timeout=8000):
    """Seleciona item de select Ark/React de forma robusta.

    Em alguns pontos da Lexio o menu é renderizado fora do container do campo e
    os IDs mudam a cada tela. Por isso tentamos: data-value, role=option, texto,
    click JS e, por fim, Enter no item destacado.
    """
    texts = texts or []
    end_time = time.time() + (timeout / 1000)
    last_err = None
    while time.time() < end_time:
        if value is not None:
            selectors = [
                f"[role='option'][data-value='{value}']",
                f"[data-scope='select'][data-part='item'][data-value='{value}']",
                f"div[data-value='{value}']",
            ]
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.count() and force_click(loc, timeout=1200):
                        return True
                except Exception as e:
                    last_err = e
        for text in texts:
            candidates = [
                page.locator("[role='option'], [data-scope='select'][data-part='item'], div[data-value]").filter(has_text=text).first,
                page.get_by_text(text, exact=True).first,
                page.get_by_text(text, exact=False).first,
            ]
            for loc in candidates:
                try:
                    if force_click(loc, timeout=1200):
                        return True
                except Exception as e:
                    last_err = e
        try:
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            return True
        except Exception as e:
            last_err = e
        page.wait_for_timeout(300)
    return False


def open_select_by_current_value_or_label(page, current_text=None, label_texts=None, fallback_index=0, timeout=8000):
    """Abre um combobox priorizando o botão que mostra um texto atual."""
    if current_text:
        try:
            loc = page.locator("button[role='combobox']").filter(has_text=current_text).first
            if force_click(loc, timeout=timeout):
                return True
        except Exception:
            pass
    return click_combobox_near_label(page, label_texts or [], fallback_index=fallback_index, timeout=timeout)


def click_combobox_near_label(page, label_texts, fallback_index=0, timeout=8000):
    """Abre um combobox. Primeiro tenta pelo texto de label próximo; depois usa índice fallback."""
    if isinstance(label_texts, str):
        label_texts = [label_texts]
    for label in label_texts:
        try:
            # Tenta localizar o campo em um container que contenha o label.
            loc = page.locator("div, section, form").filter(has_text=label).locator("button[role='combobox']").first
            if force_click(loc, timeout=timeout):
                return True
        except Exception:
            pass
    try:
        loc = page.locator("button[role='combobox']").nth(fallback_index)
        return force_click(loc, timeout=timeout)
    except Exception:
        return False


def fill_selector(page, selector, value, timeout=5000):
    if value is None:
        return False
    try:
        loc = first_visible(page, selector, timeout=timeout)
        loc.fill(str(value), timeout=timeout)
        return True
    except Exception:
        return False


def fill_first_visible_input(page, labels_or_placeholders, value, timeout=3000):
    if not value:
        return False
    if isinstance(labels_or_placeholders, str):
        labels_or_placeholders = [labels_or_placeholders]
    for lab in labels_or_placeholders:
        try:
            page.get_by_label(lab).fill(value, timeout=timeout)
            return True
        except Exception:
            pass
        try:
            page.get_by_placeholder(lab).fill(value, timeout=timeout)
            return True
        except Exception:
            pass
    try:
        inputs = page.locator("input:visible")
        for i in range(min(inputs.count(), 12)):
            inp = inputs.nth(i)
            try:
                if not norm_text(inp.input_value(timeout=800)):
                    inp.fill(value, timeout=timeout)
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _visible_text_if_any(page, selectors, timeout=800):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=timeout):
                txt = norm_text(loc.inner_text(timeout=timeout))
                if txt:
                    return txt
        except Exception:
            pass
    return ""


def _click_login_submit(page, timeout=5000):
    """Confirma formulários de login Keycloak/Lexio de forma mais tolerante."""
    selectors = [
        "button#kc-login",
        "input#kc-login",
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Entrar')",
        "button:has-text('Continuar')",
        "button:has-text('Acessar')",
        "input[value='Entrar']",
        "input[value='Continuar']",
        "[role='button']:has-text('Entrar')",
        "[role='button']:has-text('Continuar')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=1200):
                try:
                    loc.scroll_into_view_if_needed(timeout=1200)
                except Exception:
                    pass
                try:
                    loc.click(timeout=timeout)
                    return True
                except Exception:
                    try:
                        loc.evaluate("el => el.click()", timeout=timeout)
                        return True
                    except Exception:
                        pass
        except Exception:
            pass
    try:
        page.keyboard.press("Enter")
        return True
    except Exception:
        return False


def login_if_needed(page, email, password, start_url):
    log("Abrindo Lexio...")
    if not norm_text(email):
        email = DEFAULT_LOGIN_EMAIL
    if not password:
        password = DEFAULT_LOGIN_PASSWORD
    if not password:
        raise RuntimeError("A senha da Lexio não foi carregada nem no padrão local. Reexecute usar_credenciais_padrao.cmd.")

    page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    password_attempts = 0
    username_attempts = 0
    last_url = ""

    for _ in range(120):
        url = page.url
        if url != last_url:
            log("Página atual: " + url.split('?')[0])
            last_url = url

        if "app.lexio.legal" in url and "openid-connect" not in url and "login" not in url.lower():
            log("Sessão Lexio detectada.")
            return

        error_msg = _visible_text_if_any(page, [
            "#input-error",
            ".kc-feedback-text",
            ".alert-error",
            ".pf-c-alert__title",
            "[class*='error']",
            "[aria-live='polite']",
        ])
        if error_msg and any(p in error_msg.lower() for p in ["invál", "inval", "incorrect", "senha", "password", "credencial", "credential"]):
            raise RuntimeError("A Lexio recusou o login: " + error_msg + " Verifique as credenciais salvas no configurar_credenciais.cmd.")

        user_loc = page.locator("input#username, input[name='username'], input[type='email'], input[name='email']").first
        try:
            if user_loc.count() and user_loc.is_visible(timeout=800):
                current = ""
                try:
                    current = user_loc.input_value(timeout=800)
                except Exception:
                    pass
                if norm_text(current).lower() != norm_text(email).lower():
                    username_attempts += 1
                    log("Preenchendo login da Lexio...")
                    user_loc.fill("", timeout=3000)
                    user_loc.type(email, delay=20, timeout=10000)
                if username_attempts <= 4:
                    _click_login_submit(page)
                    page.wait_for_timeout(1800)
                elif password_attempts == 0:
                    try:
                        page.keyboard.press("Tab")
                        page.wait_for_timeout(300)
                    except Exception:
                        pass
        except Exception:
            pass

        pass_loc = page.locator("input#password, input[name='password'], input[type='password']").first
        try:
            if pass_loc.count() and pass_loc.is_visible(timeout=800):
                password_attempts += 1
                log(f"Preenchendo senha da Lexio... tentativa {password_attempts}")
                try:
                    pass_loc.click(timeout=3000)
                    pass_loc.fill("", timeout=3000)
                    pass_loc.type(str(password), delay=25, timeout=15000)
                except Exception:
                    fill_selector(page, "input#password, input[name='password'], input[type='password']", password)
                page.wait_for_timeout(500)
                _click_login_submit(page)
                page.wait_for_timeout(3500)
                if password_attempts >= 4:
                    error_msg = _visible_text_if_any(page, [
                        "#input-error",
                        ".kc-feedback-text",
                        ".alert-error",
                        ".pf-c-alert__title",
                        "[class*='error']",
                        "body",
                    ], timeout=1000)
                    if error_msg:
                        small = error_msg[:500]
                        raise RuntimeError("A tela de senha permaneceu aberta após 4 tentativas. Mensagem da página: " + small)
                    raise RuntimeError("A tela de senha permaneceu aberta após 4 tentativas. Reconfigure a senha e teste o login manualmente uma vez no Chrome aberto pelo agente.")
        except RuntimeError:
            raise
        except Exception:
            pass

        time.sleep(1)
    raise RuntimeError("Não foi possível concluir o login na Lexio dentro do tempo esperado.")



def select_lexio_folder(page, folder="Procurações e Substabelecimentos - QCA"):
    """Seleciona a pasta Lexio antes do tipo de contrato.

    Pasta esperada: Procurações e Substabelecimentos - QCA (data-value 114277).
    O id do componente é dinâmico, então a automação tenta pelo label/texto
    e cai no primeiro combobox da tela quando necessário.
    """
    log(f"Selecionando pasta Lexio: {folder}...")
    # Às vezes a pasta já vem selecionada. Confere primeiro para evitar clique desnecessário.
    try:
        if page.locator("button[role='combobox']").filter(has_text=folder).count():
            log("Pasta Lexio já selecionada.")
            return True
    except Exception:
        pass

    opened = click_combobox_near_label(
        page,
        ["Pasta", "Pasta de trabalho", "Procurações e Substabelecimentos"],
        fallback_index=0,
        timeout=9000,
    )
    if not opened:
        raise RuntimeError("Não consegui abrir o campo Pasta da Lexio.")
    page.wait_for_timeout(700)
    if not click_option_by_value_or_text(
        page,
        value="114277" if folder == "Procurações e Substabelecimentos - QCA" else None,
        texts=[folder],
        timeout=9000,
    ):
        raise RuntimeError(f"Não consegui selecionar a pasta {folder}.")
    page.wait_for_timeout(700)
    if not page.locator("button[role='combobox']").filter(has_text=folder).count():
        raise RuntimeError(f"Não consegui confirmar a pasta {folder}.")
    return True


def select_contract_type(page, doc_type="interno", contract_type=""):
    doc_key = norm_text(doc_type or "interno").lower()
    if "procur" in doc_key:
        contract_full = "Queiroz Cavalcanti | Procuração"
        contract_short = "Procuração"
    elif "extern" in doc_key:
        contract_full = "Queiroz Cavalcanti | Substabelecimento Cliente"
        contract_short = "Substabelecimento Cliente"
    else:
        contract_full = "Queiroz Cavalcanti | Substabelecimento Outros"
        contract_short = "Substabelecimento Outros"

    if contract_type:
        contract_full = contract_type
        contract_short = contract_type
    log(f"Selecionando tipo de contrato: {contract_full}...")
    # A tela tem pelo menos dois selects: pasta e tipo de contrato.
    opened = False
    try:
        combos = page.locator("button[role='combobox']")
        count = combos.count()
        for i in range(count):
            combo = combos.nth(i)
            try:
                txt = norm_text(combo.inner_text(timeout=800))
                if "Procurações e Substabelecimentos" in txt:
                    continue
                if (not txt) or "Tipo" in txt or "contrato" in txt.lower():
                    if force_click(combo, timeout=2500):
                        opened = True
                        break
            except Exception:
                continue
    except Exception:
        opened = False
    if not opened:
        opened = click_combobox_near_label(page, ["Tipo de contrato", "Tipo", "Contrato"], fallback_index=1, timeout=9000)
    if not opened:
        raise RuntimeError("Não consegui abrir o campo Tipo de contrato.")
    page.wait_for_timeout(900)

    ok = click_option_by_value_or_text(
        page,
        value=None,
        texts=[contract_full, contract_short],
        timeout=12000,
    )

    def contract_is_selected():
        try:
            combos = page.locator("button[role='combobox']")
            target = norm_text(contract_short).lower()
            for i in range(combos.count()):
                txt = norm_text(combos.nth(i).inner_text(timeout=800)).lower()
                if target and target in txt:
                    return True
        except Exception:
            pass
        return False

    if not contract_is_selected():
        ok = False
        # Reabre o campo e busca explicitamente pelo nome do contrato para não aceitar
        # uma opção padrão incorreta quando a lista muda de ordem.
        try:
            click_combobox_near_label(page, ["Tipo de contrato", "Tipo", "Contrato"], fallback_index=1, timeout=5000)
            page.wait_for_timeout(400)
            page.keyboard.type(contract_short, delay=20)
            page.wait_for_timeout(700)
            page.keyboard.press("Enter")
            page.wait_for_timeout(700)
            ok = contract_is_selected()
        except Exception:
            ok = False
    if not ok:
        raise RuntimeError(f"Não consegui selecionar o tipo de contrato {contract_short}.")
    page.wait_for_timeout(1000)

def upload_document(page, file_path, glpi_id="A PREENCHER", doc_type="interno", folder="Procurações e Substabelecimentos - QCA", contract_type=""):
    log(f"Subindo arquivo: {Path(file_path).name}")
    # Pode usar link direto ou o botão da home.
    page.goto("https://app.lexio.legal/document-upload", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)
    try:
        page.locator("input[type=file]").first.set_input_files(file_path, timeout=30000)
    except Exception:
        click_selector(page, "a[data-testid='lexio-subir-documentos']", timeout=5000)
        page.wait_for_timeout(1500)
        page.locator("input[type=file]").first.set_input_files(file_path, timeout=30000)
    page.wait_for_timeout(2500)
    log("Arquivo Word carregado.")

    select_lexio_folder(page, folder=folder)
    select_contract_type(page, doc_type=doc_type, contract_type=contract_type)

    # Documento não está assinado.
    click_selector(page, "input[data-testid='upload-not-signed'], input#signed-2", timeout=4000)
    page.wait_for_timeout(300)

    if not click_selector(page, "button[data-testid='upload-submit']", timeout=8000):
        click_by_text(page, ["Enviar", "Continuar"], timeout=6000)
    page.wait_for_timeout(2500)

    # ID GLPI
    fill_selector(page, "input[data-testid^='upload-detail-ID GLPI'], input[placeholder='ID GLPI']", glpi_id, timeout=6000)
    page.wait_for_timeout(500)
    if not click_selector(page, "button[data-testid='upload-submit']", timeout=8000):
        click_by_text(page, ["Enviar", "Continuar"], timeout=6000)
    log("Documento enviado/criado. Aguardando página do contrato...")
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    if "/empresa/contrato/" not in page.url:
        page.wait_for_timeout(5000)
    if "/empresa/contrato/" not in page.url:
        log("Atenção: a URL ainda não parece ser de contrato, mas vou prosseguir.")
    link = page.url
    log(f"Link do contrato: {link}")
    return link


def open_signature_flow(page):
    log("Abrindo fluxo de assinatura eletrônica...")
    if not click_selector(page, "a[data-testid='document-sign']", timeout=12000):
        if not click_by_text(page, ["Assinar eletronicamente", "Assinar"], timeout=12000):
            raise RuntimeError("Não encontrei o botão Assinar eletronicamente.")
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    if not click_selector(page, "a[data-testid='sign-gateway-lexio']", timeout=8000):
        click_by_text(page, ["Lexio", "certificado", "Certificado"], timeout=5000)
    page.wait_for_timeout(3000)


def click_signer_result(page, signer_name, timeout=10000):
    """Seleciona o card do signatário após a busca. O card costuma ter <p>Nome</p><span>email</span>."""
    signer_name = norm_text(signer_name)
    candidates = [signer_name, signer_name.title()]
    end_time = time.time() + (timeout / 1000)
    while time.time() < end_time:
        for name in candidates:
            try:
                loc = page.locator("div").filter(has=page.locator("p", has_text=name)).first
                if force_click(loc, timeout=1500):
                    return True
            except Exception:
                pass
            try:
                loc = page.locator("div, label, li, [role='option']").filter(has_text=name).first
                if force_click(loc, timeout=1500):
                    return True
            except Exception:
                pass
        page.wait_for_timeout(500)
    return False


def select_signer_type_parte(page):
    """Seleciona o tipo do signatário como advogado no modal da Lexio.

    Ajuste isolado sobre a base v48. Não altera leitura/tratamento da planilha.
    Usa o combobox indicado pela Lexio e confirma a seleção antes de seguir.
    """
    log("Selecionando tipo do signatário: advogado...")

    def _txt(s):
        try:
            return norm_text(s or "").lower()
        except Exception:
            return (s or "").strip().lower()

    def verify_selected():
        # Verifica se algum select visível do modal mostra exatamente advogado.
        try:
            triggers = page.locator("button[role='combobox'][data-scope='select'][data-part='trigger']:visible")
            for i in range(triggers.count()):
                try:
                    t = _txt(triggers.nth(i).inner_text(timeout=400))
                    if t == "advogado" or "advogado" in t:
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if page.locator("[data-scope='select'][data-part='value-text']", has_text=re.compile(r"^\s*advogado\s*$", re.I)).count():
                return True
        except Exception:
            pass
        return False

    if verify_selected():
        log("Tipo do signatário já está como advogado.")
        return True

    def click_any(loc, timeout=1800):
        try:
            loc.wait_for(state="visible", timeout=timeout)
            loc.scroll_into_view_if_needed(timeout=timeout)
        except Exception:
            pass
        for mode in ("click", "force", "events", "js"):
            try:
                if mode == "click":
                    loc.click(timeout=timeout)
                elif mode == "force":
                    loc.click(timeout=timeout, force=True)
                elif mode == "events":
                    loc.dispatch_event("pointerdown", {"button": 0, "buttons": 1, "bubbles": True})
                    loc.dispatch_event("mousedown", {"button": 0, "buttons": 1, "bubbles": True})
                    loc.dispatch_event("mouseup", {"button": 0, "buttons": 0, "bubbles": True})
                    loc.dispatch_event("click", {"button": 0, "bubbles": True})
                else:
                    loc.evaluate("el => el.click()", timeout=timeout)
                return True
            except Exception:
                pass
        return False

    def open_tipo_select():
        # 1) XPath informado pela usuária, quando o ID dinâmico coincide.
        exact_xpaths = [
            "//*[@id='select:_r_4_:trigger']",
            "//*[contains(@id, 'select:') and contains(@id, ':trigger') and @role='combobox' and .//*[contains(normalize-space(.), 'Tipo de signatário')]]",
        ]
        for xp in exact_xpaths:
            try:
                loc = page.locator("xpath=" + xp).first
                if loc.count() and click_any(loc, timeout=1500):
                    return True
            except Exception:
                pass

        # 2) JS: encontra o trigger cujo texto/área contém "Tipo de signatário".
        try:
            ok = page.evaluate("""
            () => {
              const norm = s => (s || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();
              const triggers = Array.from(document.querySelectorAll('button[role="combobox"][data-scope="select"][data-part="trigger"], [data-scope="select"][data-part="trigger"]'));
              let target = triggers.find(el => norm(el.innerText).includes('tipo de signatario'));
              if (!target) {
                target = triggers.find(el => {
                  const box = el.closest('div');
                  return box && norm(box.innerText).includes('tipo de signatario');
                });
              }
              if (!target) target = triggers[triggers.length - 1];
              if (!target) return false;
              target.scrollIntoView({block:'center', inline:'center'});
              target.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true, button:0, buttons:1}));
              target.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, button:0, buttons:1}));
              target.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, button:0}));
              target.click();
              return true;
            }
            """)
            if ok:
                return True
        except Exception:
            pass

        # 3) Fallback: último combobox visível do modal.
        try:
            triggers = page.locator("button[role='combobox'][data-scope='select'][data-part='trigger']:visible, [data-scope='select'][data-part='trigger']:visible")
            for i in range(triggers.count() - 1, -1, -1):
                try:
                    txt = _txt(triggers.nth(i).inner_text(timeout=300))
                    if "procura" in txt or "substabelecimento" in txt or "contrato" in txt:
                        continue
                except Exception:
                    pass
                if click_any(triggers.nth(i), timeout=1200):
                    return True
        except Exception:
            pass
        return False

    def click_advogado_option():
        # A lista é renderizada fora do modal. Clicar no item pai, não apenas no span.
        selectors = [
            "[role='option'][data-value='advogado']",
            "[data-scope='select'][data-part='item'][data-value='advogado']",
            "div[data-value='advogado']",
            "xpath=//*[@id='select:_r_4_:option:advogado']",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).filter(has_text=re.compile(r"^\s*advogado\s*$", re.I)).first
                if loc.count() and click_any(loc, timeout=1500):
                    return True
            except Exception:
                pass
            try:
                loc = page.locator(sel).first
                if loc.count() and click_any(loc, timeout=1500):
                    return True
            except Exception:
                pass
        try:
            spans = page.locator("span[data-scope='select'][data-part='item-text']").filter(has_text=re.compile(r"^\s*advogado\s*$", re.I))
            for i in range(spans.count()):
                sp = spans.nth(i)
                try:
                    item = sp.locator("xpath=ancestor::*[@role='option' or @data-part='item'][1]").first
                    if item.count() and click_any(item, timeout=1500):
                        return True
                except Exception:
                    pass
                if click_any(sp, timeout=1500):
                    return True
        except Exception:
            pass
        try:
            opt = page.get_by_role("option", name=re.compile(r"^\s*advogado\s*$", re.I)).first
            if opt.count() and click_any(opt, timeout=1500):
                return True
        except Exception:
            pass
        # Último recurso: teclado, útil quando a lista abre mas o clique não prende.
        try:
            page.keyboard.press("End")
            page.wait_for_timeout(100)
            page.keyboard.press("Enter")
            return True
        except Exception:
            pass
        return False

    for attempt in range(4):
        if verify_selected():
            log("Tipo do signatário selecionado: advogado.")
            return True
        if not open_tipo_select():
            log(f"Tentativa {attempt+1}: não consegui abrir o campo Tipo de signatário.")
            page.wait_for_timeout(250)
            continue
        page.wait_for_timeout(250)
        if click_advogado_option():
            page.wait_for_timeout(450)
            if verify_selected():
                log("Tipo do signatário selecionado: advogado.")
                return True
        page.wait_for_timeout(350)

    log("Não confirmei a seleção do tipo advogado; o campo pode continuar obrigatório.")
    return False


def signer_name_email(signer):
    """Aceita signatário como string ou dict {name,email}."""
    if isinstance(signer, dict):
        return norm_text(signer.get("name") or signer.get("nome") or ""), norm_text(signer.get("email") or signer.get("e-mail") or "")
    return norm_text(signer), ""


def signer_kind(signer):
    """Tipo esperado na Lexio: advogado ou parte.

    O site envia `type: parte` para documentos assinados por cliente e
    `type: advogado` para documentos internos assinados por gestor/diretor.
    """
    if isinstance(signer, dict):
        t = norm_text(signer.get("type") or signer.get("tipo") or signer.get("kind") or "advogado").lower()
        if "parte" in t or "cliente" in t:
            return "parte"
    return "advogado"


def select_signer_type(page, kind="advogado"):
    kind = (kind or "advogado").lower()
    if kind != "parte":
        return select_signer_type_parte(page)
    log("Selecionando tipo do signatário: Parte...")
    try:
        # Se já estiver selecionado, segue.
        if page.locator("[data-scope='select'][data-part='value-text']", has_text=re.compile(r"^\s*parte\s*$", re.I)).count():
            return True
    except Exception:
        pass
    try:
        open_select_by_current_value_or_label(page, current_text="advogado", label_texts=["Tipo de signatário", "Tipo de signatario"], fallback_index=0, timeout=8000)
        page.wait_for_timeout(300)
        if click_option_by_value_or_text(page, value="parte", texts=["Parte", "parte"], timeout=7000):
            page.wait_for_timeout(500)
            return True
    except Exception:
        pass
    # Se não confirmar Parte, não bloqueia totalmente; tenta seguir como o comportamento já validado.
    log("Não consegui confirmar o tipo Parte. Tentarei prosseguir com o comportamento padrão.")
    raise RuntimeError("Não consegui selecionar o tipo Parte; envio interrompido.")


def add_signer_by_name_email(page, signer_name, signer_email, kind="advogado"):
    """Adiciona signatário preenchendo Nome e Email diretamente.

    Usado quando a planilha de importação tem as colunas EMAIL GESTOR / EMAIL DIRETOR.
    """
    signer_name = norm_text(signer_name)
    signer_email = norm_text(signer_email)
    if not signer_name or not signer_email:
        return False
    log(f"Adicionando signatário por nome/e-mail: {signer_name} <{signer_email}>")
    if not click_selector(page, "button[data-testid='sign-submission-add-signer-certificate']", timeout=10000):
        click_by_text(page, ["Adicionar signatário", "Adicionar signatario"], timeout=8000)
    page.wait_for_timeout(1200)
    if not fill_selector(page, "input[data-testid='add-signer-name'], input#add-name, input[name='add-name'], input[placeholder='Nome']", signer_name, timeout=7000):
        fill_first_visible_input(page, ["Nome"], signer_name)
    if not fill_selector(page, "input[data-testid='add-signer-email'], input#add-email, input[name='add-email'], input[placeholder='Email'], input[type='email']", signer_email, timeout=7000):
        fill_first_visible_input(page, ["Email", "E-mail"], signer_email)
    page.wait_for_timeout(500)
    if not select_signer_type(page, kind):
        raise RuntimeError("Não consegui selecionar o tipo de signatário.")
    page.wait_for_timeout(200)
    saved = False
    for sel in [
        "button:has-text('Adicionar signatário')",
        "button:has-text('Adicionar signatario')",
        "button[type='submit']:has-text('Adicionar')",
        "button[class*='primary']:has-text('Adicionar')",
        "button:has-text('Salvar')",
    ]:
        if click_selector(page, sel, timeout=3500):
            saved = True
            break
    if not saved:
        saved = click_by_text(page, ["Adicionar signatário", "Adicionar signatario", "Adicionar", "Salvar"], timeout=8000)
    if not saved:
        raise RuntimeError(f"Não consegui adicionar o signatário {signer_name} por nome/e-mail.")
    page.wait_for_timeout(1500)
    log(f"Signatário adicionado: {signer_name}")
    return True

def add_signer(page, signer):
    signer_name, signer_email = signer_name_email(signer)
    kind = signer_kind(signer)
    if not signer_name:
        return False
    if signer_email:
        return add_signer_by_name_email(page, signer_name, signer_email, kind)
    # Fallback: quando não houver e-mail, usa a busca da Lexio por nome.
    log(f"Adicionando signatário por busca: {signer_name}")
    if not click_selector(page, "button[data-testid='sign-submission-add-signer-certificate']", timeout=10000):
        click_by_text(page, ["Adicionar signatário", "Adicionar signatario"], timeout=8000)
    page.wait_for_timeout(1200)
    # Buscar signatário
    if not fill_selector(page, "input[name='search-signer'], input[placeholder='Buscar signatário'], input[role='combobox']", signer_name, timeout=6000):
        fill_first_visible_input(page, ["Buscar signatário", "Buscar signatario"], signer_name)
    page.wait_for_timeout(2500)
    if not click_signer_result(page, signer_name, timeout=12000):
        raise RuntimeError(f"Não consegui clicar no signatário localizado: {signer_name}")
    page.wait_for_timeout(1200)
    if not select_signer_type(page, kind):
        raise RuntimeError("Não consegui selecionar o tipo de signatário.")
    page.wait_for_timeout(250)
    saved = False
    for sel in [
        "button[data-testid='edit-signer-button-save']",
        "button:has-text('Editar signatário')",
        "button:has-text('Adicionar signatário')",
        "button:has-text('Salvar')",
        "button:has-text('Confirmar')",
    ]:
        if click_selector(page, sel, timeout=3500):
            saved = True
            break
    if not saved:
        saved = click_by_text(page, ["Editar signatário", "Adicionar signatário", "Salvar", "Confirmar"], timeout=8000)
    if not saved:
        raise RuntimeError("Não consegui salvar o signatário após selecionar o tipo selecionado.")
    for _ in range(12):
        try:
            if page.locator("button[data-testid='sign-submission-add-signer-certificate']").count():
                break
        except Exception:
            pass
        page.wait_for_timeout(500)
    log(f"Signatário adicionado: {signer_name}")
    return True

def enable_signature_positioning(page):
    """Marca a opção de posicionar assinatura/carimbo antes de abrir a tela de posição."""
    log("Selecionando opção de posicionar assinatura...")
    # O checkbox pode ficar oculto por trás de um switch visual. Tentamos pelo input,
    # pelo data-testid e pelo texto/estado visual informado pela Lexio.
    selectors = [
        "input#place-stamps",
        "input[data-testid='sign-submission-sign-position']",
        "[data-testid='sign-submission-sign-position']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if not loc.count():
                continue
            checked = False
            try:
                checked = bool(loc.is_checked(timeout=1200))
            except Exception:
                pass
            if checked:
                log("Opção de posicionamento já estava selecionada.")
                return True
            try:
                loc.check(force=True, timeout=2500)
                log("Opção de posicionamento selecionada.")
                return True
            except Exception:
                try:
                    loc.evaluate("el => { if (!el.checked) { el.click(); el.dispatchEvent(new Event('change', {bubbles:true})); } }")
                    log("Opção de posicionamento selecionada via script.")
                    return True
                except Exception:
                    pass
        except Exception:
            pass
    # Fallback: clica no switch/linha visual que contém o estado de posicionamento.
    for sel in [
        "span.nFc3h1ovh3ILVMgl1tie__state",
        "span[class*='state']:has(span[class*='position'])",
        "label:has(input#place-stamps)",
        "div:has(input#place-stamps)",
    ]:
        try:
            loc = page.locator(sel).first
            if force_click(loc, timeout=2500):
                log("Opção de posicionamento selecionada pelo componente visual.")
                page.wait_for_timeout(500)
                return True
        except Exception:
            pass
    log("Atenção: não consegui confirmar a seleção da opção de posicionar assinatura. Vou tentar continuar.")
    return False



def click_position_signer_card(page, signer_name, timeout=10000):
    """Seleciona o signatário no modal de posicionamento de carimbo.

    A Lexio mostra um modal "Selecionar signatário" com um <label> contendo
    nome/e-mail e depois exige clique no botão "Posicionar assinatura".
    O fluxo anterior clicava no texto, mas não confirmava o botão do modal.
    """
    signer_name = norm_text(signer_name)
    end_time = time.time() + (timeout / 1000)
    while time.time() < end_time:
        # Se houver campo de busca no modal, filtra pelo nome.
        try:
            search = page.locator("input[placeholder*='Buscar signat'], input[placeholder*='signat'], input[type='search']").first
            if search.count():
                try:
                    search.fill(signer_name, timeout=1200)
                    page.wait_for_timeout(600)
                except Exception:
                    pass
        except Exception:
            pass
        # Clica especificamente no label/card do signatário.
        for loc in [
            page.locator("label").filter(has_text=signer_name).first,
            page.locator("label").filter(has_text=signer_name.title()).first,
            page.locator("div").filter(has=page.locator("p", has_text=signer_name)).first,
            page.locator("div").filter(has_text=signer_name).first,
            page.get_by_text(signer_name, exact=False).first,
        ]:
            try:
                if loc.count() and force_click(loc, timeout=1200):
                    page.wait_for_timeout(400)
                    return True
            except Exception:
                pass
        page.wait_for_timeout(400)
    return False


def confirm_position_signer_modal(page, timeout=10000):
    """Confirma o botão do modal 'Posicionar assinatura'."""
    end_time = time.time() + (timeout / 1000)
    while time.time() < end_time:
        for sel in [
            "button[type='submit']:has-text('Posicionar assinatura')",
            "button:has-text('Posicionar assinatura')",
            "button:has-text('Posicionar Assinatura')",
            "button[class*='primary']:has-text('Posicionar')",
        ]:
            try:
                loc = page.locator(sel).first
                if loc.count() and force_click(loc, timeout=1200):
                    page.wait_for_timeout(800)
                    return True
            except Exception:
                pass
        page.wait_for_timeout(400)
    return False


def position_signatures_best_effort(page, signers):
    log("Preparando posicionamento das assinaturas...")
    enable_signature_positioning(page)
    page.wait_for_timeout(500)
    # Lembrete 2 dias
    fill_selector(page, "input[data-testid='sign-submission-reminder'], input#reminder", "2", timeout=4000)
    page.wait_for_timeout(300)
    if not click_selector(page, "button[data-testid='sign-submission-button-position']", timeout=8000):
        click_by_text(page, ["Posicionar Assinatura", "Posicionar assinatura"], timeout=8000)
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    # rola documento até o final
    try:
        page.evaluate("""
        () => {
          const el = document.querySelector('div[class*="PDFPages"]') || document.scrollingElement || document.body;
          el.scrollTop = el.scrollHeight;
          window.scrollTo(0, document.body.scrollHeight);
        }
        """)
    except Exception:
        pass
    page.wait_for_timeout(1200)
    # Clica na ferramenta de posicionamento, seleciona o signatário no modal,
    # confirma "Posicionar assinatura" e só depois clica no PDF.
    for idx, signer in enumerate(signers[:6]):
        try:
            log(f"Posicionando carimbo {idx + 1}/{min(len(signers), 6)}: {signer}")
            opened = False
            for sel in [
                "button[aria-label*='Posicionar assinatura']",
                "button[aria-label*='rubrica']",
                "button:has(svg):visible",
            ]:
                try:
                    loc = page.locator(sel).first
                    if loc.count() and force_click(loc, timeout=2500):
                        opened = True
                        break
                except Exception:
                    pass
            if not opened:
                raise RuntimeError("não consegui clicar na ferramenta de posicionamento")
            page.wait_for_timeout(900)

            if not click_position_signer_card(page, signer, timeout=10000):
                raise RuntimeError(f"não consegui selecionar o card/label do signatário {signer}")
            if not confirm_position_signer_modal(page, timeout=10000):
                raise RuntimeError("não consegui confirmar o botão Posicionar assinatura do modal")

            # Depois de confirmar o modal, o carimbo fica preso ao cursor.
            # Clica acima dos nomes no rodapé: gestor à esquerda, diretor à direita.
            page.wait_for_timeout(1000)
            try:
                page.evaluate("""
                () => {
                  const el = document.querySelector('div[class*="PDFPages"]') || document.scrollingElement || document.body;
                  el.scrollTop = el.scrollHeight;
                  window.scrollTo(0, document.body.scrollHeight);
                }
                """)
            except Exception:
                pass
            page.wait_for_timeout(600)
            canvas = page.locator("canvas").last
            box = canvas.bounding_box(timeout=6000)
            if not box:
                raise RuntimeError("não encontrei o canvas do documento")
            # Posições ajustadas conforme validação visual: gestor bem à esquerda
            # e diretor bem à direita, na área final do documento.
            # A Lexio posiciona o carimbo a partir do ponto clicado; por isso
            # usamos pontos mais afastados do centro para evitar que o carimbo
            # fique no meio da página.
            # Ajuste solicitado: carimbos quase no rodapé do documento,
            # com gestor bem mais à esquerda e diretor bem mais à direita.
            # Mantemos o clique dentro do canvas para evitar que a Lexio rejeite o posicionamento.
            x_ratio = 0.08 if idx % 2 == 0 else 0.58
            rows = (len(signers) + 1) // 2
            y_ratio = 0.86 - (rows - 1 - idx // 2) * 0.10
            x = box["x"] + box["width"] * x_ratio
            y = box["y"] + box["height"] * y_ratio
            page.mouse.click(x, y)
            log(f"Carimbo posicionado para {signer} em x={x_ratio:.2f}, y={y_ratio:.2f}.")
            page.wait_for_timeout(1200)
        except Exception as e:
            raise RuntimeError(f"Não consegui posicionar a assinatura de {signer}; envio interrompido: {e}") from e
    # Alguns fluxos exigem botão voltar/salvar posicionamento; tenta enviar depois mesmo assim.


def send_for_signature(page):
    log("Enviando para assinatura...")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1000)
    if not click_selector(page, "button[data-testid='sign-submission-save']", timeout=12000):
        if not click_by_text(page, ["Enviar para assinatura", "Enviar"], timeout=12000):
            raise RuntimeError("Não encontrei o botão Enviar para assinatura.")
    page.wait_for_timeout(1500)
    click_by_text(page, ["Enviar para assinatura", "Enviar", "Confirmar", "Sim"], timeout=5000)
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    log("Documento enviado para assinatura ou solicitação concluída.")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python lexio_rpa.py manifest.json")
    manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    files = manifest.get("files") or []
    start_url = manifest.get("url") or "https://app.lexio.legal/empresa/dashboard"
    email = manifest.get("login_email") or DEFAULT_LOGIN_EMAIL
    password = manifest.get("login_password") or DEFAULT_LOGIN_PASSWORD
    signers = [s for s in (manifest.get("signers") or [manifest.get("signer") or ""]) if (norm_text(s.get("name") if isinstance(s, dict) else s))]
    glpi_id = manifest.get("glpi_id") or "A PREENCHER"
    result_json = Path(manifest.get("result_json") or "resultado_lexio.json")
    action = manifest.get("action") or ("upload_only" if manifest.get("upload_only") else "sign")
    metadata = manifest.get("metadata") or {}
    doc_type = metadata.get("docType") or metadata.get("doc_type") or "interno"
    headless = bool(manifest.get("headless", False))

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        log("Dependência ausente: playwright. Execute instalar_dependencias.bat.")
        log(str(e))
        raise

    results = []
    with sync_playwright() as p:
        profile_dir = Path(os.getenv("APPDATA") or Path.home()) / "Lexio_RPA_QCA_Profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        log("Abrindo Google Chrome em modo controlado...")
        context = p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=headless,
            channel="chrome",
            accept_downloads=True,
            args=[] if headless else ["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(25000)
        login_if_needed(page, email, password, start_url)
        for idx, file_path in enumerate(files, start=1):
            file_path = str(file_path)
            log(f"[{idx}/{len(files)}] Iniciando {Path(file_path).name}")
            try:
                link = upload_document(page, file_path, glpi_id=glpi_id, doc_type=doc_type, folder=metadata.get("folder") or "Procurações e Substabelecimentos - QCA", contract_type=metadata.get("contract_type") or "")
                if action == "sign":
                    open_signature_flow(page)
                    selected_signers = signers[:6]
                    for sidx, signer in enumerate(selected_signers, start=1):
                        signer_display, _signer_email = signer_name_email(signer)
                        log(f"Selecionando signatário {sidx}/{len(selected_signers)}: {signer_display}...")
                        add_signer(page, signer)
                    position_signatures_best_effort(page, [signer_name_email(s)[0] for s in selected_signers])
                    send_for_signature(page)
                    final_link = page.url if "/empresa/contrato/" in page.url else link
                else:
                    log("Documento externo/procuração: somente upload na Lexio, sem envio para assinatura.")
                    final_link = page.url if "/empresa/contrato/" in page.url else link
                results.append({"file": file_path, "status": "OK", "url": final_link})
                log(f"[{idx}/{len(files)}] OK - {final_link}")
            except Exception as e:
                results.append({"file": file_path, "status": "ERRO", "error": str(e), "url": page.url})
                log(f"[{idx}/{len(files)}] ERRO - {Path(file_path).name}: {e}")
        result_json.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        log("Resultado salvo em: " + str(result_json))
        # mantém o Chrome aberto por alguns segundos para conferência visual.
        page.wait_for_timeout(2500)
        context.close()


if __name__ == "__main__":
    main()
