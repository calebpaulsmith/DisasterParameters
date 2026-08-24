Attribute VB_Name = "modChartA"
Option Explicit

' =====================================================================
' PA PDAs ChartA Builder - Table A (+ optional Chart A's) -> pa_pdas_charta
'
' Excel twin of pdaboard/pa_pdas_charta.py + the Databricks notebook:
'   1. Run BuildChartaTable (button on the Builder sheet, or Alt+F8).
'   2. Browse to the folder holding the PDA's Table A workbook (Chart A
'      workbooks anywhere under the same folder are used for comment /
'      applicant-type / inspector enrichment when present - OPTIONAL).
'   3. Verify the PDA identity prompts (Year / Month / State /
'      Declaration number) - defaults come from the Table A itself.
'   4. Rows land on the pa_pdas_charta sheet as an Excel Table
'      (ListObject) - Power BI: Get Data > Excel workbook > pa_pdas_charta.
'
' Handles BOTH Table A template generations by reading LABELS, not fixed
' cells:  v2 (RVAR-era, IN 2026) and legacy (SummaryPage/PCI Indicator,
' MI/WI 2026).  The existing pa_pdas table is NEVER touched: the link is
' the shared natural key, exposed as Pda_Id = Year-Month-State.  If a
' sheet named pa_pdas holds an extract of the existing table (headers in
' row 1), a best-effort row-level link fills In_Pa_Pdas /
' Pa_Pdas_Applicant_Name - optional; no match is fine.
'
' Null convention mirrors pa_pdas: blank/0 category cells stay EMPTY,
' Total = sum of the non-empty categories.  Comment_Html is left empty
' here (the Databricks pipeline fills it; Excel keeps plain Comment).
' OpenFEMA reference data belongs on the separate "openfema" sheet -
' this macro never writes there.
' =====================================================================

Public Sub BuildChartaTable()
    Dim folder As String
    With Application.FileDialog(msoFileDialogFolderPicker)
        .Title = "Pick the folder holding this PDA's Table A (and Chart A's)"
        If .Show = 0 Then Exit Sub
        folder = .SelectedItems(1)
    End With
    Dim msg As String
    msg = BuildChartaCore(folder, "", "", "", "", True, True)
    If msg <> "" Then MsgBox msg, vbInformation, "pa_pdas_charta"
End Sub

Public Function BuildChartaAuto(folder As String, yr As String, mo As String, _
        st As String, dn As String, useCharts As Boolean) As String
    ' non-interactive twin (automation / testing): identity values are used
    ' as given, falling back to the Table A defaults when blank
    BuildChartaAuto = BuildChartaCore(folder, yr, mo, st, dn, useCharts, False)
End Function

Private Function BuildChartaCore(folder As String, argYr As String, _
        argMo As String, argSt As String, argDn As String, _
        useCharts As Boolean, interactive As Boolean) As String
    Dim fso As Object: Set fso = CreateObject("Scripting.FileSystemObject")
    Dim files As Collection, f As Variant

    Set files = New Collection
    CollectXlsx fso, fso.GetFolder(folder), files

    Dim prevCalc As Long: prevCalc = Application.Calculation
    Application.ScreenUpdating = False
    Application.Calculation = xlCalculationManual   ' opens recalc otherwise
    Application.EnableEvents = False
    Application.DisplayAlerts = False
    On Error GoTo fail

    ' ---- classify: Table A's and Chart A's
    Dim tblPath As String, tblSize As Double
    Dim chartPaths As Collection: Set chartPaths = New Collection
    For Each f In files
        Select Case SniffKind(CStr(f))
            Case "table_a"
                If fso.GetFile(f).Size > tblSize Then
                    tblSize = fso.GetFile(f).Size: tblPath = f
                End If
            Case "chart_a"
                chartPaths.Add f
        End Select
    Next f
    If tblPath = "" Then
        BuildChartaCore = "No Table A workbook found under" & vbLf & folder
        GoTo cleanup
    End If

    ' ---- parse the Table A
    Dim wb As Workbook
    Set wb = Workbooks.Open(tblPath, ReadOnly:=True, UpdateLinks:=0)
    Dim meta As Object: Set meta = ParseTableAMeta(wb)
    Dim subs As Collection: Set subs = ParseSubrecipients(wb)
    Dim ctys As Object: Set ctys = ParseCountyTable(wb, meta)
    wb.Close SaveChanges:=False

    ' ---- verify PDA identity (defaults from the workbook)
    Dim yr As String, mo As String, st As String, dn As String
    If interactive Then
        yr = InputBox("PDA year (pa_pdas Year):", "Verify PDA", meta("def_year"))
        If yr = "" Then GoTo cleanup
        mo = InputBox("PDA month (pa_pdas Month, e.g. May):", "Verify PDA", meta("def_month"))
        If mo = "" Then GoTo cleanup
        st = UCase$(InputBox("State (2-letter):", "Verify PDA", meta("state_code")))
        If st = "" Then GoTo cleanup
        dn = InputBox("Declaration number (blank if none yet):", "Verify PDA", "")
    Else
        yr = IIf(argYr <> "", argYr, CStr(meta("def_year")))
        mo = IIf(argMo <> "", argMo, CStr(meta("def_month")))
        st = UCase$(IIf(argSt <> "", argSt, CStr(meta("state_code"))))
        dn = argDn
        If yr = "" Or mo = "" Or st = "" Then
            BuildChartaCore = "PDA identity incomplete (year/month/state) and no Table A default"
            GoTo cleanup
        End If
    End If
    Dim pdaId As String: pdaId = yr & "-" & mo & "-" & st

    ' ---- optional Chart A enrichment
    Dim chartApps As Object: Set chartApps = CreateObject("Scripting.Dictionary")
    Dim chartMeta As Object: Set chartMeta = CreateObject("Scripting.Dictionary")
    Dim nCharts As Long, wantCharts As Boolean
    wantCharts = useCharts
    If interactive And chartPaths.Count > 0 Then
        wantCharts = (MsgBox(chartPaths.Count & " Chart A workbook(s) found - read " & _
                  "them for comments / applicant types / inspectors? (No = Table A only)", _
                  vbYesNo + vbQuestion, "Chart A enrichment") = vbYes)
    End If
    If wantCharts Then
        For Each f In chartPaths
            nCharts = nCharts + ReadChartA(CStr(f), chartApps, chartMeta)
        Next f
    End If

    ' ---- optional pa_pdas link source
    Dim link As Object: Set link = LoadPaPdasLink(yr, mo, st)

    ' ---- compose rows
    Dim out As Worksheet: Set out = EnsureSheet("pa_pdas_charta")
    Dim ofm As Worksheet: Set ofm = EnsureSheet("openfema")
    If ofm.Range("A1").Value = "" Then _
        ofm.Range("A1").Value = "Reserved for OpenFEMA reference data (prior PA history) - separate table, imported separately."
    Do While out.ListObjects.Count > 0
        out.ListObjects(1).Unlist
    Loop
    out.Cells.Clear

    Dim hdr As Variant
    hdr = Array("Charta_Id", "Pda_Id", "Year", "Month", "State", "State_Pop", _
        "State_Threshold", "Declaration_Number", "County", "Met_Threshold", _
        "County_Pop", "County_Threshold", "Applicant_Id", "SLTT_Organization_Id", _
        "Applicant_Name", "Cat_A", "Cat_B", "Cat_C", "Cat_D", "Cat_E", "Cat_F", _
        "Cat_G", "Total", "Status", "Applicant_Type", "Comment", "Comment_Html", _
        "Inspector", "Source_File", "In_Pa_Pdas", "Pa_Pdas_Applicant_Name")
    Dim c As Long
    For c = 0 To UBound(hdr): out.Cells(1, c + 1).Value = hdr(c): Next c

    Dim statePop As Variant: statePop = meta("state_population")
    Dim stateThr As Variant
    If Not IsEmpty(statePop) And Not IsEmpty(meta("state_pci")) Then _
        stateThr = Round(CDbl(statePop) * CDbl(meta("state_pci")), 2)

    Dim r As Long: r = 1
    Dim rowTotal As Double, subTotal As Double, nLinked As Long, nComment As Long
    Dim s As Variant
    For Each s In SortedSubs(subs)
        r = r + 1
        Dim county As String: county = CountyShort(s(1))
        Dim ck As String: ck = LCase$(county)
        Dim pop As Variant, thr As Variant, ctot As Variant
        pop = Empty: thr = Empty: ctot = Empty
        If ctys.Exists(ck) Then
            pop = ctys(ck)(0): thr = ctys(ck)(1): ctot = ctys(ck)(2)
        End If
        out.Cells(r, 1).Value = pdaId & "-" & Format$(r - 1, "0000")
        out.Cells(r, 2).Value = pdaId
        out.Cells(r, 3).Value = CLng(yr)
        out.Cells(r, 4).Value = mo
        out.Cells(r, 5).Value = st
        If Not IsEmpty(statePop) Then out.Cells(r, 6).Value = statePop
        If Not IsEmpty(stateThr) Then out.Cells(r, 7).Value = stateThr
        If dn <> "" Then out.Cells(r, 8).Value = dn
        out.Cells(r, 9).Value = county
        If IsNumeric(thr) And IsNumeric(ctot) Then _
            out.Cells(r, 10).Value = (CDbl(ctot) >= CDbl(thr))
        If Not IsEmpty(pop) Then out.Cells(r, 11).Value = pop
        If Not IsEmpty(thr) Then out.Cells(r, 12).Value = thr
        out.Cells(r, 15).Value = s(0)
        Dim i As Long, tot As Double, anyCat As Boolean: tot = 0: anyCat = False
        For i = 0 To 6
            If s(3 + i) <> 0 Then
                out.Cells(r, 16 + i).Value = Round(s(3 + i), 2)
                tot = tot + Round(s(3 + i), 2): anyCat = True
            End If
        Next i
        If anyCat Then out.Cells(r, 23).Value = Round(tot, 2): rowTotal = rowTotal + tot
        If s(2) <> "" Then out.Cells(r, 24).Value = s(2)
        ' Chart A enrichment: match by county + normalized name (with the
        ' 'X - County' multi-county suffix stripped)
        Dim ak As String
        ak = ck & "|" & NormName(StripCountySuffix(CStr(s(0)), county))
        If Not chartApps.Exists(ak) Then ak = ck & "|" & NormName(CStr(s(0)))
        If chartApps.Exists(ak) Then
            Dim ca As Variant: ca = chartApps(ak)
            If ca(0) <> "" Then out.Cells(r, 25).Value = ca(0)
            If ca(1) <> "" Then out.Cells(r, 26).Value = ca(1): nComment = nComment + 1
        End If
        If chartMeta.Exists(ck) Then If chartMeta(ck) <> "" Then out.Cells(r, 28).Value = chartMeta(ck)
        out.Cells(r, 29).Value = fso.GetFileName(tblPath)
        ' pa_pdas best-effort link (only when a pa_pdas sheet is present)
        If Not link Is Nothing Then
            Dim hit As String
            hit = FindLink(link, county, CStr(s(0)))
            If hit = "" Then hit = FindLink(link, county, StripCountySuffix(CStr(s(0)), county))
            out.Cells(r, 30).Value = (hit <> "")
            If hit <> "" Then out.Cells(r, 31).Value = hit: nLinked = nLinked + 1
        End If
        subTotal = subTotal + s(10)
    Next s

    ' ---- dollar conservation (same gate as the python/Databricks builders)
    If Abs(rowTotal - subTotal) > Application.Max(0.01, 0.005 * (r - 1)) Then
        BuildChartaCore = "DOLLAR CONSERVATION FAILED: rows $" & _
               Format$(rowTotal, "#,##0.00") & " vs Table A $" & _
               Format$(subTotal, "#,##0.00") & vbLf & _
               "Output NOT trustworthy - check the Table A layout."
        If interactive Then MsgBox BuildChartaCore, vbCritical: BuildChartaCore = ""
        GoTo cleanup
    End If

    ' ---- ListObject for one-click Power BI import
    Dim lo As ListObject
    On Error Resume Next
    Set lo = out.ListObjects("pa_pdas_charta")
    On Error GoTo fail
    If lo Is Nothing Then
        Set lo = out.ListObjects.Add(xlSrcRange, _
            out.Range(out.Cells(1, 1), out.Cells(r, UBound(hdr) + 1)), , xlYes)
        lo.Name = "pa_pdas_charta"
    Else
        lo.Resize out.Range(out.Cells(1, 1), out.Cells(r, UBound(hdr) + 1))
    End If
    out.Columns.AutoFit

    BuildChartaCore = "pa_pdas_charta built: " & (r - 1) & " rows, $" & _
           Format$(rowTotal, "#,##0.00") & vbLf & _
           "Pda_Id " & pdaId & " | " & ctys.Count & " counties" & _
           IIf(nCharts > 0, " | " & nComment & " comments from Chart A's", "") & _
           IIf(Not link Is Nothing, " | " & nLinked & " linked to pa_pdas", "") & vbLf & _
           "Power BI: Get Data > Excel workbook > table pa_pdas_charta."
cleanup:
    Application.Calculation = prevCalc
    Application.EnableEvents = True
    Application.DisplayAlerts = True
    Application.ScreenUpdating = True
    Exit Function
fail:
    Application.Calculation = prevCalc
    Application.EnableEvents = True
    Application.DisplayAlerts = True
    Application.ScreenUpdating = True
    BuildChartaCore = "Error: " & Err.Description
    If interactive Then MsgBox BuildChartaCore, vbCritical: BuildChartaCore = ""
End Function

' ------------------------------------------------------------- discovery

Private Sub CollectXlsx(fso As Object, fld As Object, files As Collection)
    Dim f As Object, sub_ As Object
    For Each f In fld.files
        If LCase$(fso.GetExtensionName(f.Name)) = "xlsx" _
           And Left$(f.Name, 2) <> "~$" Then files.Add f.Path
    Next f
    For Each sub_ In fld.SubFolders
        CollectXlsx fso, sub_, files
    Next sub_
End Sub

Private Function SniffKind(path As String) As String
    ' sheet names only - mirrors chart_a_parser.sniff_workbook
    Dim wb As Workbook, names As String, ws As Worksheet
    On Error GoTo bad
    Set wb = Workbooks.Open(path, ReadOnly:=True, UpdateLinks:=0)
    For Each ws In wb.Worksheets: names = names & "|" & ws.Name: Next ws
    wb.Close SaveChanges:=False
    If InStr(names, "|County Summary") > 0 Then
        SniffKind = "chart_a"
    ElseIf InStr(names, "|Input Sheet") > 0 And _
           (InStr(names, "|RVAR") > 0 Or InStr(names, "|SummaryPage") > 0 _
            Or InStr(names, "|PCI Indicator") > 0) Then
        SniffKind = "table_a"
    Else
        SniffKind = "other"
    End If
    Exit Function
bad:
    SniffKind = "other"
End Function

' ------------------------------------------------------------- Table A

Private Function ParseTableAMeta(wb As Workbook) As Object
    ' label-driven Input Sheet header (works for v2 AND legacy), with the
    ' legacy PCI Indicator sheet as the population/PCI fallback
    Dim m As Object: Set m = CreateObject("Scripting.Dictionary")
    Dim ws As Worksheet: Set ws = wb.Worksheets("Input Sheet")
    Dim r As Long, c As Long, v As Variant, key As String
    For r = 1 To 3
        For c = 1 To 13
            v = ws.Cells(r, c).Value
            If VarType(v) = vbString Then
                If Right$(Trim$(v), 1) = ":" Then
                    key = LCase$(Trim$(Left$(Trim$(v), Len(Trim$(v)) - 1)))
                    If Not m.Exists(key) Then m(key) = ws.Cells(r, c + 1).Value
                End If
            End If
        Next c
    Next r
    Dim d As Object: Set d = CreateObject("Scripting.Dictionary")
    d("state_code") = Trim$(CStr(NzS(m, "state code")))
    d("state_population") = NzN(m, "population")
    d("state_pci") = NzN(m, "state per capita")
    d("county_pci") = NzN(m, "county per capita")
    d("pda_start") = NzS(m, "pda start")
    d("incident_start") = NzS(m, "incident start")

    On Error Resume Next
    Dim pws As Worksheet: Set pws = wb.Worksheets("PCI Indicator")
    On Error GoTo 0
    If Not pws Is Nothing Then
        For r = 1 To 40
            If UCase$(Trim$(CStr(pws.Cells(r, 1).Value))) = "STATE/TERRITORY" Then
                ' NB: IsEmpty, not IsNumeric - IsNumeric(Empty) is True in VBA
                If IsEmpty(d("state_population")) Then _
                    d("state_population") = Round(NzCell(pws.Cells(r + 1, 2)), 0)
                If IsEmpty(d("state_pci")) Then d("state_pci") = NzCell(pws.Cells(r + 1, 3))
                If IsEmpty(d("county_pci")) Then d("county_pci") = NzCell(pws.Cells(r + 1, 4))
            End If
        Next r
    End If

    Dim ref As Variant: ref = d("pda_start")
    If Not IsDate(ref) Then ref = d("incident_start")
    If IsDate(ref) Then
        d("def_year") = CStr(Year(CDate(ref)))
        d("def_month") = MonthName(Month(CDate(ref)))
    Else
        d("def_year") = "": d("def_month") = ""
    End If
    Set ParseTableAMeta = d
End Function

Private Function ParseSubrecipients(wb As Workbook) As Collection
    ' rows under the Subrecipient|County|Status|A..G header; stop at 'Total'
    ' (v2) or end of data (legacy has no Total row)
    ' item = Array(name, county, status, catA..catG, total)  (0..10)
    Dim ws As Worksheet: Set ws = wb.Worksheets("Input Sheet")
    Dim out As New Collection
    Dim hdr As Long, r As Long, i As Long
    hdr = 4
    For r = 1 To 10
        If Trim$(CStr(ws.Cells(r, 1).Value)) = "Subrecipient" Then hdr = r: Exit For
    Next r
    For r = hdr + 1 To 2000
        Dim nm As String: nm = Trim$(CStr(ws.Cells(r, 1).Value))
        If LCase$(nm) = "total" Then Exit For
        Dim cty As String: cty = Trim$(CStr(ws.Cells(r, 2).Value))
        If nm = "" And cty = "" Then GoTo nextRow
        Dim a(0 To 10) As Variant
        a(0) = nm: a(1) = cty: a(2) = Trim$(CStr(ws.Cells(r, 3).Value))
        Dim tot As Double: tot = 0
        For i = 0 To 6
            a(3 + i) = NzCell(ws.Cells(r, 4 + i))
            tot = tot + a(3 + i)
        Next i
        a(10) = tot
        out.Add a
nextRow:
    Next r
    Set ParseSubrecipients = out
End Function

Private Function ParseCountyTable(wb As Workbook, meta As Object) As Object
    ' county(lcase) -> Array(pop, threshold, entered total)
    Dim d As Object: Set d = CreateObject("Scripting.Dictionary")
    Dim ws As Worksheet, hdr As Long, r As Long

    On Error Resume Next
    Set ws = wb.Worksheets("Summary")
    On Error GoTo 0
    If Not ws Is Nothing Then
        hdr = FindHeaderRow(ws, "County", "Population", 60)
        If hdr > 0 Then
            For r = hdr + 1 To hdr + 400
                Dim cty As String: cty = Trim$(CStr(ws.Cells(r, 1).Value))
                If cty = "" Then Exit For
                d(LCase$(CountyShort(cty))) = Array( _
                    NzCell(ws.Cells(r, 2)), NzOpt(ws.Cells(r, 11)), NzOpt(ws.Cells(r, 10)))
            Next r
            Set ParseCountyTable = d: Exit Function
        End If
    End If

    Set ws = Nothing
    On Error Resume Next
    Set ws = wb.Worksheets("SummaryPage")
    On Error GoTo 0
    If Not ws Is Nothing Then
        hdr = FindHeaderRow(ws, "County", "Subrecipient", 80)
        If hdr > 0 Then
            Dim cpci As Variant: cpci = meta("county_pci")
            For r = hdr + 1 To hdr + 400
                cty = Trim$(CStr(ws.Cells(r, 1).Value))
                If cty = "" Then GoTo nextR          ' subrecipient detail row
                If LCase$(cty) = "grand total" Or LCase$(cty) = "total" Then Exit For
                Dim pop As Variant: pop = NzOpt(ws.Cells(r, 11))
                Dim thr As Variant
                If IsNumeric(pop) And IsNumeric(cpci) Then _
                    thr = Round(CDbl(pop) * CDbl(cpci), 2)
                d(LCase$(CountyShort(cty))) = Array(pop, thr, NzOpt(ws.Cells(r, 10)))
nextR:
            Next r
        End If
    End If
    Set ParseCountyTable = d
End Function

' ------------------------------------------------------------- Chart A

Private Function ReadChartA(path As String, apps As Object, metaD As Object) As Long
    ' apps("county|normname") = Array(type, comment)   metaD("county") = inspector
    Dim wb As Workbook, ws As Worksheet
    On Error GoTo bad
    Set wb = Workbooks.Open(path, ReadOnly:=True, UpdateLinks:=0)
    Set ws = wb.Worksheets("County Summary")
    Dim b3 As String: b3 = Trim$(CStr(ws.Range("B3").Value))
    Dim rx As Object: Set rx = CreateObject("VBScript.RegExp")
    rx.Pattern = "^(.+?)\s*\(\s*([\d,]+)\s*\)\s*-\s*\$\s*([\d,.]+)\s*$"
    If Not rx.Test(b3) Then GoTo done          ' county dropdown not set - skip
    Dim county As String: county = CountyShort(Trim$(rx.Execute(b3)(0).SubMatches(0)))
    Dim ck As String: ck = LCase$(county)
    If Not metaD.Exists(ck) Then metaD(ck) = Trim$(CStr(ws.Range("D3").Value))

    ' comments sheet: 'Comments' (v2) or 'Deduction Comments' (legacy)
    Dim cmts As Object: Set cmts = CreateObject("Scripting.Dictionary")
    Dim cws As Worksheet, r As Long
    On Error Resume Next
    Set cws = wb.Worksheets("Comments")
    If cws Is Nothing Then Set cws = wb.Worksheets("Deduction Comments")
    On Error GoTo bad
    If Not cws Is Nothing Then
        For r = 2 To 500
            Dim who As Variant: who = cws.Cells(r, 1).Value
            If Not IsEmpty(who) And CStr(who) <> "0" And Trim$(CStr(who)) <> "" Then
                If Trim$(CStr(cws.Cells(r, 2).Value)) <> "" Then _
                    cmts(NormName(CStr(who))) = Trim$(CStr(cws.Cells(r, 2).Value))
            End If
        Next r
    End If

    For r = 6 To 505
        Dim nm As Variant: nm = ws.Cells(r, 2).Value
        If IsEmpty(nm) Or CStr(nm) = "0" Or Trim$(CStr(nm)) = "" Then Exit For
        Dim k As String: k = ck & "|" & NormName(CStr(nm))
        Dim cmt As String
        If cmts.Exists(NormName(CStr(nm))) Then cmt = cmts(NormName(CStr(nm))) Else cmt = ""
        If Not apps.Exists(k) Then _
            apps(k) = Array(Trim$(CStr(ws.Cells(r, 3).Value)), cmt)
        ReadChartA = ReadChartA + 1
    Next r
done:
    wb.Close SaveChanges:=False
    Exit Function
bad:
    On Error Resume Next
    If Not wb Is Nothing Then wb.Close SaveChanges:=False
End Function

' ------------------------------------------------------------- pa_pdas link

Private Function LoadPaPdasLink(yr As String, mo As String, st As String) As Object
    ' optional: a sheet named pa_pdas with the existing table's extract
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets("pa_pdas")
    On Error GoTo 0
    If ws Is Nothing Then Exit Function
    If Trim$(CStr(ws.Cells(1, 1).Value)) = "" Then Exit Function
    Dim cols As Object: Set cols = CreateObject("Scripting.Dictionary")
    Dim c As Long
    For c = 1 To 40
        Dim h As String: h = Trim$(CStr(ws.Cells(1, c).Value))
        If h <> "" Then cols(h) = c
    Next c
    If Not (cols.Exists("Year") And cols.Exists("Month") And cols.Exists("State") _
            And cols.Exists("County") And cols.Exists("Applicant_Name")) Then Exit Function
    Dim d As Object: Set d = CreateObject("Scripting.Dictionary")
    Dim r As Long
    For r = 2 To ws.Cells(ws.Rows.Count, cols("Year")).End(xlUp).Row
        If Trim$(CStr(ws.Cells(r, cols("Year")).Value)) = yr _
           And LCase$(Trim$(CStr(ws.Cells(r, cols("Month")).Value))) = LCase$(mo) _
           And UCase$(Trim$(CStr(ws.Cells(r, cols("State")).Value))) = st Then
            Dim nm As String: nm = CStr(ws.Cells(r, cols("Applicant_Name")).Value)
            d(LCase$(Trim$(CStr(ws.Cells(r, cols("County")).Value))) & "|" & NormName(nm)) = nm
        End If
    Next r
    Set LoadPaPdasLink = d
End Function

Private Function FindLink(link As Object, county As String, name As String) As String
    Dim k As String
    k = LCase$(county) & "|" & NormName(name)
    If link.Exists(k) Then FindLink = link(k): Exit Function
    k = "multiple|" & NormName(name)
    If link.Exists(k) Then FindLink = link(k)
End Function

' ------------------------------------------------------------- helpers

Private Function FindHeaderRow(ws As Worksheet, a As String, b As String, maxR As Long) As Long
    Dim r As Long
    For r = 1 To maxR
        If Trim$(CStr(ws.Cells(r, 1).Value)) = a _
           And Trim$(CStr(ws.Cells(r, 2).Value)) = b Then
            FindHeaderRow = r: Exit Function
        End If
    Next r
End Function

Private Function SortedSubs(subs As Collection) As Collection
    ' stable sort by county + applicant so Charta_Id numbering is reproducible
    Dim arr() As Variant, i As Long, j As Long, t As Variant
    If subs.Count = 0 Then Set SortedSubs = subs: Exit Function
    ReDim arr(1 To subs.Count)
    For i = 1 To subs.Count: arr(i) = subs(i): Next i
    For i = 1 To UBound(arr) - 1
        For j = i + 1 To UBound(arr)
            If LCase$(arr(j)(1) & "|" & arr(j)(0)) < LCase$(arr(i)(1) & "|" & arr(i)(0)) Then
                t = arr(i): arr(i) = arr(j): arr(j) = t
            End If
        Next j
    Next i
    Dim out As New Collection
    For i = 1 To UBound(arr): out.Add arr(i): Next i
    Set SortedSubs = out
End Function

Public Function NormName(s As String) As String
    ' mirror of pa_pdas_charta.norm_appl_name: trim/casefold/collapse,
    ' 'X, City of' -> 'city of X', strip punctuation
    Dim t As String: t = Trim$(s)
    Do While InStr(t, "  ") > 0: t = Replace(t, "  ", " "): Loop
    If Right$(t, 1) = "." Then t = Left$(t, Len(t) - 1)
    Dim rx As Object: Set rx = CreateObject("VBScript.RegExp")
    rx.IgnoreCase = True
    rx.Pattern = "^(.+?),\s*(city|village|town|township|county|charter township)\s+of\s*$"
    If rx.Test(t) Then
        Dim m As Object: Set m = rx.Execute(t)(0)
        t = m.SubMatches(1) & " of " & m.SubMatches(0)
    End If
    t = LCase$(t)
    Dim i As Long, ch As String, o As String
    For i = 1 To Len(t)
        ch = Mid$(t, i, 1)
        If ch Like "[a-z0-9]" Or ch = " " Or ch = "&" Then o = o & ch Else o = o & " "
    Next i
    Do While InStr(o, "  ") > 0: o = Replace(o, "  ", " "): Loop
    NormName = Trim$(o)
End Function

Private Function StripCountySuffix(name As String, county As String) As String
    Dim n As String: n = Trim$(name)
    Dim suf As Variant
    For Each suf In Array(" - " & county, " - " & county & " County", _
                          " - " & county & " Co.", " - " & county & " Co", "- " & county)
        If county <> "" And LCase$(Right$(n, Len(suf))) = LCase$(CStr(suf)) Then
            StripCountySuffix = Trim$(Left$(n, Len(n) - Len(suf)))
            Exit Function
        End If
    Next suf
    StripCountySuffix = n
End Function

Private Function CountyShort(v As Variant) As String
    Dim s As String: s = Trim$(CStr(v))
    If LCase$(Right$(s, 7)) = " county" Then s = Trim$(Left$(s, Len(s) - 7))
    CountyShort = s
End Function

Private Function EnsureSheet(nm As String) As Worksheet
    On Error Resume Next
    Set EnsureSheet = ThisWorkbook.Worksheets(nm)
    On Error GoTo 0
    If EnsureSheet Is Nothing Then
        Set EnsureSheet = ThisWorkbook.Worksheets.Add(After:= _
            ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        EnsureSheet.Name = nm
    End If
End Function

Private Function NzCell(c As Range) As Double
    If IsNumeric(c.Value) And Not IsEmpty(c.Value) Then NzCell = CDbl(c.Value)
End Function

Private Function NzOpt(c As Range) As Variant
    If IsNumeric(c.Value) And Not IsEmpty(c.Value) Then NzOpt = CDbl(c.Value) Else NzOpt = Empty
End Function

Private Function NzS(m As Object, k As String) As Variant
    If m.Exists(k) Then NzS = m(k) Else NzS = ""
End Function

Private Function NzN(m As Object, k As String) As Variant
    If m.Exists(k) Then
        If IsNumeric(m(k)) Then NzN = CDbl(m(k)) Else NzN = Empty
    Else
        NzN = Empty
    End If
End Function
