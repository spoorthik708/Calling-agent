"use client";

import React, { useState, useEffect } from "react";
import { Navigation } from "@/components/Navigation";
import {
  PhoneCall,
  Search,
  Filter,
  Clock,
  Play,
  X,
  RefreshCw,
  PhoneIncoming,
  PhoneOutgoing,
  AlertCircle,
  FileText,
} from "lucide-react";

interface CallSession {
  id: string;
  tenant_id: string;
  agent_id: string;
  conversation_id?: string;
  voice_session_id?: string;
  provider_call_id: string;
  telephony_provider: string;
  direction: string;
  from_phone: string;
  to_phone: string;
  status: string;
  recording_url?: string;
  error_message?: string;
  duration_seconds: number;
  started_at?: string;
  ended_at?: string;
  created_at: string;
}

export default function CallHistoryPage() {
  const [calls, setCalls] = useState<CallSession[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [directionFilter, setDirectionFilter] = useState<string>("all");
  const [selectedCall, setSelectedCall] = useState<CallSession | null>(null);

  const fetchCallHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const queryParams = new URLSearchParams();
      if (statusFilter !== "all") queryParams.append("status", statusFilter);
      if (directionFilter !== "all") queryParams.append("direction", directionFilter);

      const res = await fetch(`/api/v1/telephony/calls?${queryParams.toString()}`, {
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!res.ok) {
        throw new Error(`Failed to fetch call history (${res.status})`);
      }

      const data = await res.json();
      setCalls(data);
    } catch (err: any) {
      setError(err.message || "An error occurred while loading call history.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCallHistory();
  }, [statusFilter, directionFilter]);

  const filteredCalls = calls.filter((call) => {
    const q = searchQuery.toLowerCase();
    return (
      call.from_phone.toLowerCase().includes(q) ||
      call.to_phone.toLowerCase().includes(q) ||
      call.provider_call_id.toLowerCase().includes(q)
    );
  });

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  const getStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case "completed":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "failed":
      case "busy":
      case "no_answer":
        return "bg-rose-500/10 text-rose-400 border-rose-500/20";
      case "in_progress":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse";
      case "ringing":
      case "queued":
        return "bg-purple-500/10 text-purple-400 border-purple-500/20";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navigation />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-purple-900/20 pb-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-100">Call History</h1>
            <p className="text-xs text-slate-400 mt-1">
              Real-time audit log of all inbound and outbound PSTN/SIP phone calls.
            </p>
          </div>
          <button
            onClick={fetchCallHistory}
            className="self-start md:self-auto flex items-center space-x-2 px-3.5 py-2 rounded-xl text-xs font-medium bg-purple-900/20 text-purple-300 border border-purple-500/30 hover:bg-purple-900/40 transition duration-200"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Search and Filters */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {/* Search */}
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-3 text-slate-500" />
            <input
              type="text"
              placeholder="Search phone number or call ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2.5 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500/50"
            />
          </div>

          {/* Direction Filter */}
          <div className="flex items-center space-x-2 bg-slate-900/80 border border-slate-800 rounded-xl px-3 py-2">
            <Filter className="w-4 h-4 text-slate-500" />
            <select
              value={directionFilter}
              onChange={(e) => setDirectionFilter(e.target.value)}
              className="bg-transparent text-xs text-slate-200 focus:outline-none w-full"
            >
              <option value="all" className="bg-slate-900">All Directions</option>
              <option value="inbound" className="bg-slate-900">Inbound</option>
              <option value="outbound" className="bg-slate-900">Outbound</option>
            </select>
          </div>

          {/* Status Filter */}
          <div className="flex items-center space-x-2 bg-slate-900/80 border border-slate-800 rounded-xl px-3 py-2">
            <Filter className="w-4 h-4 text-slate-500" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-transparent text-xs text-slate-200 focus:outline-none w-full"
            >
              <option value="all" className="bg-slate-900">All Statuses</option>
              <option value="completed" className="bg-slate-900">Completed</option>
              <option value="in_progress" className="bg-slate-900">In Progress</option>
              <option value="ringing" className="bg-slate-900">Ringing / Queued</option>
              <option value="failed" className="bg-slate-900">Failed / Busy</option>
            </select>
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center space-x-3 text-xs text-rose-300">
            <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Call List Table */}
        <div className="rounded-2xl bg-slate-900/60 border border-purple-900/20 backdrop-blur-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/90 text-slate-400 uppercase font-mono text-[10px] tracking-wider border-b border-slate-800">
                <tr>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4">Direction</th>
                  <th className="px-6 py-4">From / To</th>
                  <th className="px-6 py-4">Duration</th>
                  <th className="px-6 py-4">Date & Time</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {loading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i} className="animate-pulse">
                      <td className="px-6 py-4"><div className="h-4 w-16 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-16 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-32 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-12 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-24 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4 text-right"><div className="h-4 w-12 bg-slate-800 rounded-md ml-auto" /></td>
                    </tr>
                  ))
                ) : filteredCalls.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-500">
                      <PhoneCall className="w-8 h-8 mx-auto mb-2 text-slate-600" />
                      <p>No call sessions match your filter criteria.</p>
                    </td>
                  </tr>
                ) : (
                  filteredCalls.map((call) => (
                    <tr key={call.id} className="hover:bg-slate-800/40 transition duration-150">
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-medium border ${getStatusBadge(call.status)}`}>
                          {call.status}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className="flex items-center space-x-1.5 font-mono text-slate-300">
                          {call.direction === "inbound" ? (
                            <PhoneIncoming className="w-3.5 h-3.5 text-sky-400" />
                          ) : (
                            <PhoneOutgoing className="w-3.5 h-3.5 text-purple-400" />
                          )}
                          <span className="capitalize">{call.direction}</span>
                        </span>
                      </td>
                      <td className="px-6 py-4 font-mono text-slate-200">
                        <div><span className="text-slate-500">From:</span> {call.from_phone}</div>
                        <div><span className="text-slate-500">To:</span> {call.to_phone}</div>
                      </td>
                      <td className="px-6 py-4 font-mono text-slate-300">
                        {formatDuration(call.duration_seconds)}
                      </td>
                      <td className="px-6 py-4 text-slate-400">
                        {new Date(call.created_at).toLocaleString()}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => setSelectedCall(call)}
                          className="px-3 py-1.5 rounded-lg bg-purple-900/30 text-purple-300 border border-purple-500/20 hover:bg-purple-900/50 transition duration-150"
                        >
                          Details
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Call Details Modal */}
        {selectedCall && (
          <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-purple-900/40 rounded-2xl max-w-lg w-full p-6 space-y-5 shadow-2xl">
              <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                <div className="flex items-center space-x-2">
                  <FileText className="w-4 h-4 text-purple-400" />
                  <h3 className="text-base font-semibold text-slate-100">Call Session Details</h3>
                </div>
                <button
                  onClick={() => setSelectedCall(null)}
                  className="text-slate-400 hover:text-slate-200"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-3 text-xs text-slate-300">
                <div className="flex justify-between border-b border-slate-800/60 pb-2">
                  <span className="text-slate-500">Call Session ID:</span>
                  <span className="font-mono text-slate-200">{selectedCall.id}</span>
                </div>
                <div className="flex justify-between border-b border-slate-800/60 pb-2">
                  <span className="text-slate-500">Provider Call ID:</span>
                  <span className="font-mono text-slate-200">{selectedCall.provider_call_id}</span>
                </div>
                <div className="flex justify-between border-b border-slate-800/60 pb-2">
                  <span className="text-slate-500">Direction:</span>
                  <span className="capitalize text-slate-200">{selectedCall.direction}</span>
                </div>
                <div className="flex justify-between border-b border-slate-800/60 pb-2">
                  <span className="text-slate-500">Status:</span>
                  <span className={`px-2 py-0.5 rounded-full border ${getStatusBadge(selectedCall.status)}`}>
                    {selectedCall.status}
                  </span>
                </div>
                <div className="flex justify-between border-b border-slate-800/60 pb-2">
                  <span className="text-slate-500">Duration:</span>
                  <span className="font-mono">{formatDuration(selectedCall.duration_seconds)}</span>
                </div>

                {/* Audio Recording Section */}
                <div className="pt-2">
                  <span className="text-slate-400 font-semibold block mb-2">Call Audio Recording</span>
                  {selectedCall.recording_url ? (
                    <div className="p-3 rounded-xl bg-slate-950 border border-purple-900/30">
                      <audio controls src={selectedCall.recording_url} className="w-full h-8" />
                    </div>
                  ) : (
                    <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 text-slate-500 italic">
                      No recording available for this call session.
                    </div>
                  )}
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  onClick={() => setSelectedCall(null)}
                  className="px-4 py-2 rounded-xl bg-slate-800 text-slate-200 text-xs hover:bg-slate-700"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
