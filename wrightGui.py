from collections import defaultdict
import sys
from wx.lib.pubsub import setupkwargs
from wx.lib.pubsub import pub
import wx
import wx.lib.mixins.listctrl as listmix
import os

class CandidateObj(object):
    def __init__(self,name,id=0):
        self.name=name
        self.id=id


class WrightModel():

    def __init__(self):
        self.settings=dict()
        self.settings['fname']=''
        self.exclusions = list()
        self.settings['seats'] = 14
        #self.settings['auditlog'] = "auditLog.txt"

        
    def prepareCandidates(self):
        #Yes, this is processing the entire file, just to get the candidate names. Messy, but it works.
        fp = open(self.settings['fname'], "r")
        numCandidates, numSeats = (int(x) for x in fp.readline().split(" "))
        remainingCandidates = set(range(1, numCandidates + 1))
        intline = [int(x) for x in fp.readline().split(" ")]
        if intline[0] < 0:
            for failboat in intline:
                remainingCandidates.remove(-failboat)
            intline = [int(x) for x in fp.readline().split(" ")]
        vectors = []
        while intline[0] != 0:
            vectors.append([intline[0], intline[1:]])  # [X votes, voteVector]
            intline = [int(x) for x in fp.readline().split(" ")]
        candidateNames = ["Exhausted"]  # Use candidate 0 as the sentinel for exhausted ballots
        for _ in xrange(numCandidates):
            candidateNames.append(fp.readline().strip("\n"))
        electionName = fp.readline()
        fp.close()
        self.candidates=candidateNames
    

    def doElection(self):
        fp = open(self.settings['fname'], "r")

        numCandidates, numSeats = (int(x) for x in fp.readline().split(" "))
        numSeats = self.settings['seats'] # Overriding the number in the file
        remainingCandidates = set(range(1, numCandidates + 1)) # Candidate numbers count starting at 1, 0 is the terminator

        # If our numbers here on the second line are negative, it means they've withdrawn
        intline = [int(x) for x in fp.readline().split(" ")]
        if intline[0] < 0:
            for failboat in intline:
                remainingCandidates.remove(-failboat)
            intline = [int(x) for x in fp.readline().split(" ")]

        for exclude in self.exclusions:
            remainingCandidates.remove(int(exclude))

        # We're now in the vote block, go 'til we hit a "0" row.
        vectors = []
        while intline[0] != 0:
            vectors.append([intline[0], intline[1:]])  # [X votes, voteVector]
            intline = [int(x) for x in fp.readline().split(" ")]

        candidateNames = ["Exhausted"]  # Use candidate 0 as the sentinel for exhausted ballots
        for _ in xrange(numCandidates):
            candidateNames.append(fp.readline().strip("\n"))

        electionName = fp.readline()
        fp.close()


        while len(remainingCandidates) > numSeats:
            self.set_status_text("Candidates Remaining",0)
            self.set_status_text(str(len(remainingCandidates)),1)
            wx.Yield()
            winningCandidates = []

            # Establish the working copy of the vectors, of the format
            # [remainingWeight, [remainingVector]]
            # filtering out candidates that are no longer in the vote.
            weightedVectors = [[weight, [candidate for candidate in vec if candidate in remainingCandidates]] for weight, vec in vectors]

            # Count up the vectors that have at least one candidate in them in order to form the quota
            electorateSize = 0
            for weight, vector in weightedVectors:
                if vector:
                    electorateSize += weight
            droopQuota = int(electorateSize / float(numSeats + 1) + 1)

            candidateEliminated = None

            # We're going to loop around awarding seats and distributing surpluses until noone is worthy and all the
            # surpluses are distributed.  At that point we eliminate someone, terminate this loop, and restart from the top.
            while candidateEliminated is None and len(winningCandidates) < numSeats:
                # Sum up the top preferences of the current vectors by candidate
                accumulator = defaultdict(float)
                for weight, vector in weightedVectors:
                    if vector:
                        accumulator[vector[0]] += weight
                # Listify and sort from most votes to least votes.  Notably, ties are broken here by going to the 2nd
                # element of the tuple and using the candidate index (higher is better).  While not an ideal way to break
                # ties, it's clean and repeatable, while still being random as the candidates are indexed in random order
                # in the .blt file.  This is only unfair if a candidate is involved in two ties, a rather unlikely occurance.
                votesPerCandidate = sorted([(votes, candidate) for candidate, votes in accumulator.iteritems()], reverse=True)

                # First, find newly provisionally elected dudes and remove them from any ballots that have them
                # listed 2nd or further down.  Provisionally elected dudes can't recieve transfer votes (they don't need them either)
                candidatesToRemove = []
                for votes, candidate in [x for x in votesPerCandidate if x[0] >= droopQuota and x[1] not in winningCandidates]:
                    candidatesToRemove.append(candidate)
                    winningCandidates.append(candidate)
                for idx, (weight, vector) in enumerate(weightedVectors):
                    if vector:
                        weightedVectors[idx][1] = [vector[0]] + [cand for cand in vector[1:] if cand not in candidatesToRemove]

                # Now, do the vote transfering for the candidate with the highest talley, if they pass quota.
                topVotes, topCandidate = max(votesPerCandidate)
                if topVotes > droopQuota:
                    overflowRatio = (topVotes - droopQuota) / topVotes

                    # Remove that ratio of weight from any vector that has this candidate as front.  You voted for a winner!
                    # Collect up the benefits - that is, the talley of 2nd preferences of voters who currently have the winner
                    # as first preference, for auditing purposes.  It's not algorythmically important.
                    transferBenefits = defaultdict(float)
                    for idx, (weight, vector) in enumerate(weightedVectors):
                        if vector and vector[0] == topCandidate:
                            weightedVectors[idx][0] = weight * overflowRatio
                            if len(vector) > 1:
                                transferBenefits[vector[1]] += weight * overflowRatio
                            else:
                                # The vector is exhaused-with-value if the winner was the last candidate listed
                                transferBenefits[0] += weight * overflowRatio

                            # And remove the winner from the front of our vector, transfering it on down.
                            weightedVectors[idx][1] = vector[1:]

                    benefitiaries = sorted([(votes, cand) for cand, votes in transferBenefits.iteritems()], reverse=True)

                else:
                    # Time to nuke someone, as our top vote-getter did not reach quota
                    votes, candidateEliminated = min(votesPerCandidate)
                    remainingCandidates.remove(candidateEliminated)

            if len(winningCandidates) == numSeats:
                # Eliminate everyone else, we've elected enough
                remainingCandidates = set(winningCandidates)

        self.winners=list()
        for candidateIdx in sorted(remainingCandidates):
            self.winners.append(candidateNames[candidateIdx])
        self.set_status_text("Election Complete",0)
        self.set_status_text("",1)
        wx.Yield()
        pub.sendMessage('Result')
        
    def set_status_text(self,data,id):
        pub.sendMessage('update_status',data=data,extra1=id)


class WrightController():
    def __init__(self,app):
        self.view = WrightView(None,-1,"Wright Election")
        self.model = WrightModel()
        self.view.Show(True)
        pub.subscribe(self.electionResults,"Result")
        self.view.runElectionButton.Bind(wx.EVT_BUTTON,self.runElection)
        self.view.chooseBallotFile.Bind(wx.EVT_BUTTON,self.chooseBallotFile)
        self.view.copyToClipboard.Bind(wx.EVT_BUTTON,self.copyToClipboard)
        pub.subscribe(self.update_status_controller,'update_status')
        pub.subscribe(self.update_exclusion,'update_exclusion')
        app.SetTopWindow(self.view)
        
        
    def runElection(self,event):
        self.model.doElection()
    
    def copyToClipboard(self,event):
        clipdata = wx.TextDataObject()
        clipdata.SetText("\n".join(self.model.winners))
        wx.TheClipboard.Open()
        wx.TheClipboard.SetData(clipdata)
        wx.TheClipboard.Close()
    
    def chooseBallotFile(self,event):
        testfile=self.view.ballotPicker()
        if testfile != 'nofile':
            self.model.settings['fname']=testfile
            self.model.prepareCandidates()
            self.view.showCandidates(self.model.candidates)
            self.view.runElectionButton.Enable()
            self.update_status_controller("Pick exclusions then run the election")
        wx.Yield()

    def electionResults(self):
        winnerlist=list()
        self.view.winnersList.DeleteAllItems()
        for candidate in self.model.winners:
                self.view.winnersList.Append([candidate])

    def update_status_controller(self,data,extra1=0):
        self.view.update_status(data,extra1)

    def update_exclusion(self,data):
        if (data[1]):
            self.model.exclusions.append(data[0]+1)
        else:
            self.model.exclusions.remove(data[0]+1)
        
        
class TestListCtrl(wx.ListCtrl, listmix.CheckListCtrlMixin, listmix.ListCtrlAutoWidthMixin):
    def __init__(self, *args, **kwargs):
        wx.ListCtrl.__init__(self, *args, **kwargs)
        listmix.CheckListCtrlMixin.__init__(self)
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        self.setResizeColumn(2)
    def OnCheckItem(self, index, flag):
        pub.sendMessage('update_exclusion',data=[index, flag])
        
        
        
        
class WrightView(wx.Frame):
    
    def __init__(self,parent,id,title):
        wx.Frame.__init__(self, parent, id, title)
        self.panel = wx.Panel(self, wx.ID_ANY)
        self.runElectionButton=wx.Button(self.panel ,id=wx.ID_ANY,label='Run Election')
        self.chooseBallotFile=wx.Button(self.panel ,id=wx.ID_ANY,label='Choose BallotFile')
        self.copyToClipboard=wx.Button(self.panel ,id=wx.ID_ANY,label='Copy To Clipboard')
        self.runElectionButton.Disable()
        self.candidateList = TestListCtrl(self.panel,size=(400,300), style=wx.LC_REPORT)
        self.winnersList = wx.ListCtrl(self.panel, size=(300,300),style=wx.LC_REPORT)
        self.candidateList.InsertColumn(0,"ID",width=50)
        self.candidateList.InsertColumn(1,"Name",width=250)
        self.winnersList.InsertColumn(0,"Name",width=300)
        self.statusbar=self.CreateStatusBar(style=0)
        self.statusbar.SetFieldsCount(2)
        self.statusbar.SetStatusWidths([-2, -1])
        self.SetStatusText("Select a Ballot file to begin",0) 
        
        
        topsizer = wx.BoxSizer(wx.VERTICAL)
        listsizer = wx.BoxSizer(wx.HORIZONTAL)
        winsizer = wx.BoxSizer(wx.HORIZONTAL)
        btnsizer = wx.BoxSizer(wx.HORIZONTAL)
        listsizer.Add(self.candidateList, 0, wx.ALL|wx.EXPAND, 5)
        listsizer.Add(self.winnersList, 0, wx.ALL|wx.EXPAND, 5)
        btnsizer.Add(self.chooseBallotFile, 0, wx.ALL|wx.EXPAND, 5)
        btnsizer.Add(self.runElectionButton, 0, wx.ALL|wx.EXPAND, 5)
        btnsizer.Add(self.copyToClipboard, 0, wx.ALL|wx.EXPAND, 5)
        topsizer.Add(listsizer, 0, wx.ALL|wx.EXPAND, 5)
        topsizer.Add(wx.StaticLine(self.panel,), 0, wx.ALL|wx.EXPAND, 5)
        topsizer.Add(winsizer, 0, wx.ALL|wx.EXPAND, 5)
        topsizer.Add(btnsizer, 0, wx.ALL|wx.EXPAND, 5)
        self.panel.SetSizer(topsizer)
        topsizer.Fit(self)
        
    def ballotPicker(self):
        file = 'nofile'
        wildcard="Ballot File (*.blt)|*.blt"
        dlg = wx.FileDialog(
            self, "Select Ballot File", os.getcwd(),"",wildcard,wx.OPEN)
        if dlg.ShowModal() == wx.ID_OK:
            file = dlg.GetPath()
        dlg.Destroy()
        return file

    def showCandidates(self,candidates):
        index=0;
        self.candidatelist=list()
        for candidate in candidates:
            if index>0:
                self.candidateList.Append([str(index),candidate])
            index += 1

    def update_status(self,data,extra1=0):
        self.SetStatusText(data,extra1)

if __name__ == '__main__':
    app = wx.App(False)
    controller = WrightController(app)
    app.MainLoop()
