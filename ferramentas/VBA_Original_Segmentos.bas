Attribute VB_Name = "Módulo1"
Sub Filtrar_Segmentos_att()

    Dim ws As Worksheet
    Dim wb As Workbook
    Dim wsResumo As Worksheet
    Dim cabecalho As Range
    Dim ultimaCelula As Range
    Dim intervaloBase As Range

    Dim colunaSegmento As Long
    Dim colunaGrupo As Long
    Dim ultimaLinha As Long
    Dim ultimaColuna As Long
    Dim i As Long

    Dim segmentos As Variant
    Dim grupos As Variant
    Dim resultado() As Variant
    Dim segmento As String
    Dim grupo As String

    Dim cache As PivotCache
    Dim tabela As PivotTable
    Dim campo As PivotField
    Dim item As PivotItem

    Dim permitidos As Object
    Dim nomesPermitidos As Variant
    Dim nome As Variant
    Dim quantidadeManter As Long

    Dim atualizacaoAnterior As Boolean
    Dim eventosAnteriores As Boolean
    Dim mensagemErro As String

    atualizacaoAnterior = Application.ScreenUpdating
    eventosAnteriores = Application.EnableEvents

    On Error GoTo TratarErro

    Set ws = ActiveSheet
    Set wb = ws.Parent

    'Localiza a coluna "Segmento".
    Set cabecalho = ws.Rows(1).Find( _
        What:="Segmento", _
        After:=ws.Cells(1, ws.Columns.Count), _
        LookIn:=xlValues, _
        LookAt:=xlWhole, _
        SearchOrder:=xlByColumns, _
        SearchDirection:=xlNext, _
        MatchCase:=False, _
        SearchFormat:=False)

    If cabecalho Is Nothing Then
        MsgBox "O cabeçalho 'Segmento' não foi encontrado na linha 1.", _
               vbExclamation
        Exit Sub
    End If

    colunaSegmento = cabecalho.Column

    'Localiza a coluna "Célula".
    Set cabecalho = ws.Rows(1).Find( _
        What:="Célula", _
        After:=ws.Cells(1, ws.Columns.Count), _
        LookIn:=xlValues, _
        LookAt:=xlWhole, _
        SearchOrder:=xlByColumns, _
        SearchDirection:=xlNext, _
        MatchCase:=False, _
        SearchFormat:=False)

    If cabecalho Is Nothing Then
        MsgBox "O cabeçalho 'Célula' não foi encontrado na linha 1.", _
               vbExclamation
        Exit Sub
    End If

    colunaGrupo = cabecalho.Column

    'Identifica a última coluna da base.
    ultimaColuna = ws.Cells(1, ws.Columns.Count).End(xlToLeft).Column

    'Identifica a última linha preenchida.
    Set ultimaCelula = ws.Range( _
        ws.Cells(1, 1), _
        ws.Cells(ws.Rows.Count, ultimaColuna)).Find( _
            What:="*", _
            After:=ws.Cells(1, 1), _
            LookIn:=xlFormulas, _
            LookAt:=xlPart, _
            SearchOrder:=xlByRows, _
            SearchDirection:=xlPrevious, _
            MatchCase:=False, _
            SearchFormat:=False)

    If ultimaCelula Is Nothing Then Exit Sub

    ultimaLinha = ultimaCelula.Row

    If ultimaLinha < 2 Then
        MsgBox "Não há registros para processar.", vbExclamation
        Exit Sub
    End If

    'Valida o campo ID usado na tabela dinâmica.
    Set cabecalho = ws.Rows(1).Find( _
        What:="ID", _
        After:=ws.Cells(1, ws.Columns.Count), _
        LookIn:=xlValues, _
        LookAt:=xlWhole, _
        SearchOrder:=xlByColumns, _
        SearchDirection:=xlNext, _
        MatchCase:=False, _
        SearchFormat:=False)

    If cabecalho Is Nothing Then
        MsgBox "O cabeçalho 'ID' não foi encontrado na linha 1.", _
               vbExclamation
        Exit Sub
    End If

    Application.ScreenUpdating = False
    Application.EnableEvents = False

    'Remove filtros para tratar toda a base.
    If ws.FilterMode Then ws.ShowAllData

    'Inclui o cabeçalho para garantir uma matriz,
    'mesmo quando existir apenas um registro.
    segmentos = ws.Range( _
        ws.Cells(1, colunaSegmento), _
        ws.Cells(ultimaLinha, colunaSegmento)).Value2

    grupos = ws.Range( _
        ws.Cells(1, colunaGrupo), _
        ws.Cells(ultimaLinha, colunaGrupo)).Value2

    ReDim resultado(1 To ultimaLinha - 1, 1 To 1)

    For i = 2 To ultimaLinha

        'Preserva o segmento atual quando nenhuma regra se aplica.
        resultado(i - 1, 1) = segmentos(i, 1)

        If Not IsError(segmentos(i, 1)) Then

            segmento = Trim$(CStr(segmentos(i, 1)))

            Select Case LCase$(segmento)

                Case "administradora de cartão de crédito", "bancário"
                    resultado(i - 1, 1) = "Bancário"

                Case "automotivo", _
                     "transporte", _
                     "transporte e lógistica", _
                     "transporte e logística"

                    resultado(i - 1, 1) = "Auto"

                Case "comércio varejista", "varejo", "varejista"
                    resultado(i - 1, 1) = "Varejo"

            End Select

        End If

        'Classifica pela palavra completa na coluna "Célula".
        'Vida e Saúde têm prioridade sobre as regras anteriores.
        If Not IsError(grupos(i, 1)) Then

            grupo = Trim$(CStr(grupos(i, 1)))

            If ContemPalavra(grupo, "Vida") Then
                resultado(i - 1, 1) = "Vida"

            ElseIf ContemPalavra(grupo, "Saúde") Then
                resultado(i - 1, 1) = "Saúde"

            End If

        End If

    Next i

    'Grava os segmentos ajustados sem alterar o cabeçalho.
    ws.Range( _
        ws.Cells(2, colunaSegmento), _
        ws.Cells(ultimaLinha, colunaSegmento)).Value2 = resultado

    Set intervaloBase = ws.Range( _
        ws.Cells(1, 1), _
        ws.Cells(ultimaLinha, ultimaColuna))

    'Cria uma nova planilha para o resumo.
    Set wsResumo = wb.Worksheets.Add( _
        After:=wb.Worksheets(wb.Worksheets.Count))

    'Cria a tabela dinâmica com o tamanho atual da base.
    Set cache = wb.PivotCaches.Create( _
        SourceType:=xlDatabase, _
        SourceData:=intervaloBase.Address( _
            ReferenceStyle:=xlR1C1, External:=True))

    cache.MissingItemsLimit = xlMissingItemsNone

    Set tabela = cache.CreatePivotTable( _
        TableDestination:=wsResumo.Range("A3"))

    With tabela

        .ColumnGrand = True
        .RowGrand = True
        .PreserveFormatting = True
        .RowAxisLayout xlCompactRow

        With .PivotFields("Segmento")
            .Orientation = xlRowField
            .Position = 1
        End With

        .AddDataField .PivotFields("ID"), _
                      "Contagem de ID", xlCount

    End With

    'Define os únicos segmentos que devem aparecer.
    Set permitidos = CreateObject("Scripting.Dictionary")
    permitidos.CompareMode = vbTextCompare

    nomesPermitidos = Array( _
        "Bancário", _
        "Auto", _
        "Varejo", _
        "Energia", _
        "Securitário", _
        "Vida", _
        "Saúde")

    For Each nome In nomesPermitidos
        permitidos(Trim$(CStr(nome))) = True
    Next nome

    Set campo = tabela.PivotFields("Segmento")
    campo.ClearAllFilters

    quantidadeManter = 0

    For Each item In campo.PivotItems

        If permitidos.Exists(Trim$(CStr(item.Name))) Then
            quantidadeManter = quantidadeManter + 1
        End If

    Next item

    'O Excel não permite ocultar todos os itens de um campo.
    If quantidadeManter = 0 Then

        wsResumo.Cells.Clear

        wsResumo.Range("A1").Value = _
            "Nenhum dos segmentos desejados foi encontrado na base."

        wsResumo.Columns("A").AutoFit

        Application.ScreenUpdating = atualizacaoAnterior
        Application.EnableEvents = eventosAnteriores

        MsgBox "Segmentos ajustados, mas nenhum dos sete " & _
               "segmentos desejados foi encontrado na base.", _
               vbInformation

        Exit Sub

    End If

    tabela.ManualUpdate = True

    'Garante que os segmentos permitidos estejam visíveis.
    For Each item In campo.PivotItems

        If permitidos.Exists(Trim$(CStr(item.Name))) Then
            item.Visible = True
        End If

    Next item

    'Oculta todos os demais segmentos.
    For Each item In campo.PivotItems

        If Not permitidos.Exists(Trim$(CStr(item.Name))) Then
            item.Visible = False
        End If

    Next item

    tabela.ManualUpdate = False
    tabela.RefreshTable

    wsResumo.Columns("A:B").AutoFit
    Application.Goto wsResumo.Range("A3"), True

    Application.ScreenUpdating = atualizacaoAnterior
    Application.EnableEvents = eventosAnteriores

    MsgBox "Segmentos ajustados e tabela dinâmica criada!", _
           vbInformation

    Exit Sub

TratarErro:

    mensagemErro = Err.Description

    On Error Resume Next

    If Not tabela Is Nothing Then
        tabela.ManualUpdate = False
    End If

    Application.ScreenUpdating = atualizacaoAnterior
    Application.EnableEvents = eventosAnteriores

    On Error GoTo 0

    MsgBox "Não foi possível concluir a macro: " & mensagemErro, _
           vbExclamation

End Sub


Private Function ContemPalavra( _
    ByVal texto As String, _
    ByVal palavra As String) As Boolean

    Static regex As Object

    If regex Is Nothing Then
        Set regex = CreateObject("VBScript.RegExp")
        regex.IgnoreCase = True
        regex.Global = False
    End If

    'Busca a palavra completa, sem diferenciar maiúsculas/minúsculas.
    'Assim, "Vida" é reconhecida, mas "Movida" não.
    regex.Pattern = _
        "(^|[^A-Za-zÀ-ÖØ-öø-ÿ0-9_])" & palavra & _
        "($|[^A-Za-zÀ-ÖØ-öø-ÿ0-9_])"

    ContemPalavra = regex.Test(texto)

End Function
