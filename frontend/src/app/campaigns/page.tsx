"use client";

import React, { useState, useEffect } from "react";
import { Navigation } from "@/components/Navigation";
import {
  Megaphone,
  Plus,
  RefreshCw,
  X,
  AlertCircle,
  Users,
  CheckCircle2,
  XCircle,
  Clock,
  Play,
  Pause,
  RotateCcw,
  ListFilter,
  Ban,
  Layers,
} from "lucide-react";

interface Campaign {
  id: string;
  tenant_id: string;
  agent_id: string;
  contact_list_id?: string;
  name: string;
  from_phone: string;
  status: string;
  target_phones: string[];
  completed_count: number;
  failed_count: number;
  skipped_count: number;
  total_count: number;
  scheduled_at?: string;
  started_at?: string;
  ended_at?: string;
  created_at: string;
}

interface CampaignTarget {
  id: string;
  phone_number: string;
  status: string;
  attempts: number;
  max_retries: number;
  provider_call_id?: string;
  last_error?: string;
  started_at?: string;
  ended_at?: string;
}

interface ContactList {
  id: string;
  name: string;
  contact_count: number;
}

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [contactLists, setContactLists] = useState<ContactList[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Modal State
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [cancellingCampaignId, setCancellingCampaignId] = useState<string | null>(null);
  const [selectedTargetsCampaign, setSelectedTargetsCampaign] = useState<Campaign | null>(null);
  const [campaignTargets, setCampaignTargets] = useState<CampaignTarget[]>([]);
  const [targetsLoading, setTargetsLoading] = useState<boolean>(false);

  // Form State
  const [formData, setFormData] = useState({
    name: "",
    agent_id: "",
    from_phone: "+18005550199",
    contact_list_id: "",
    target_phones_input: "",
    scheduled_at: "",
  });

  const fetchCampaigns = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/telephony/campaigns");
      if (!res.ok) {
        throw new Error(`Failed to fetch campaigns (${res.status})`);
      }
      const data = await res.json();
      setCampaigns(data);
    } catch (err: any) {
      setError(err.message || "Error loading campaigns.");
    } finally {
      setLoading(false);
    }
  };

  const fetchContactLists = async () => {
    try {
      const res = await fetch("/api/v1/contacts/lists");
      if (res.ok) {
        const data = await res.json();
        setContactLists(data);
      }
    } catch (err) {}
  };

  useEffect(() => {
    fetchCampaigns();
    fetchContactLists();
  }, []);

  const handleCreateCampaign = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const phones = formData.target_phones_input
      .split("\n")
      .map((p) => p.trim())
      .filter((p) => p.length > 0);

    if (!formData.contact_list_id && phones.length === 0) {
      setError("Please select a saved Contact List or provide target phone numbers.");
      return;
    }

    try {
      const payload = {
        name: formData.name,
        agent_id: formData.agent_id || "11111111-1111-1111-1111-111111111111", // Default test agent UUID
        from_phone: formData.from_phone,
        contact_list_id: formData.contact_list_id || null,
        target_phones: phones,
        scheduled_at: formData.scheduled_at ? new Date(formData.scheduled_at).toISOString() : null,
      };

      const res = await fetch("/api/v1/telephony/campaigns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to create campaign.");
      }

      setShowCreateModal(false);
      setFormData({
        name: "",
        agent_id: "",
        from_phone: "+18005550199",
        contact_list_id: "",
        target_phones_input: "",
        scheduled_at: "",
      });
      fetchCampaigns();
    } catch (err: any) {
      setError(err.message || "Error creating campaign.");
    }
  };

  const handlePauseCampaign = async (campaignId: string) => {
    try {
      const res = await fetch(`/api/v1/telephony/campaigns/${campaignId}/pause`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to pause campaign.");
      fetchCampaigns();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleResumeCampaign = async (campaignId: string) => {
    try {
      const res = await fetch(`/api/v1/telephony/campaigns/${campaignId}/resume`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to resume campaign.");
      fetchCampaigns();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleCancelCampaign = async (campaignId: string) => {
    try {
      const res = await fetch(`/api/v1/telephony/campaigns/${campaignId}/cancel`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to cancel campaign.");
      setCancellingCampaignId(null);
      fetchCampaigns();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleRetryFailed = async (campaignId: string) => {
    try {
      const res = await fetch(`/api/v1/telephony/campaigns/${campaignId}/retry-failed`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to retry failed targets.");
      fetchCampaigns();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleViewTargets = async (campaign: Campaign) => {
    setSelectedTargetsCampaign(campaign);
    setTargetsLoading(true);
    try {
      const res = await fetch(`/api/v1/telephony/campaigns/${campaign.id}/targets`);
      if (res.ok) {
        const data = await res.json();
        setCampaignTargets(data);
      }
    } catch (err) {} finally {
      setTargetsLoading(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case "running":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse";
      case "paused":
        return "bg-sky-500/10 text-sky-400 border-sky-500/20";
      case "completed":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "scheduled":
        return "bg-purple-500/10 text-purple-400 border-purple-500/20";
      case "cancelled":
        return "bg-rose-500/10 text-rose-400 border-rose-500/20";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  const getTargetStatusBadge = (st: string) => {
    switch (st.toLowerCase()) {
      case "completed":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "in_progress":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse";
      case "skipped_opt_out":
        return "bg-sky-500/10 text-sky-400 border-sky-500/20";
      case "failed":
        return "bg-rose-500/10 text-rose-400 border-rose-500/20";
      case "queued":
        return "bg-purple-500/10 text-purple-400 border-purple-500/20";
      default:
        return "bg-slate-800 text-slate-400 border-slate-700";
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navigation />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-purple-900/20 pb-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-100">Calling Campaigns</h1>
            <p className="text-xs text-slate-400 mt-1">
              Durable background campaign dispatching, retry backoff, target status tracking, and pause/resume controls.
            </p>
          </div>
          <div className="flex items-center space-x-3">
            <button
              onClick={fetchCampaigns}
              className="flex items-center space-x-2 px-3 py-2 rounded-xl text-xs font-medium bg-slate-900 text-slate-300 border border-slate-800 hover:bg-slate-800"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-medium bg-purple-600 text-white shadow-lg shadow-purple-500/20 hover:bg-purple-500 transition duration-150"
            >
              <Plus className="w-4 h-4" />
              <span>New Campaign</span>
            </button>
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center space-x-3 text-xs text-rose-300">
            <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Campaign List Table */}
        <div className="rounded-2xl bg-slate-900/60 border border-purple-900/20 backdrop-blur-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/90 text-slate-400 uppercase font-mono text-[10px] tracking-wider border-b border-slate-800">
                <tr>
                  <th className="px-6 py-4">Campaign Name</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4">Target Progress</th>
                  <th className="px-6 py-4">From Number</th>
                  <th className="px-6 py-4">Created At</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {loading ? (
                  Array.from({ length: 3 }).map((_, i) => (
                    <tr key={i} className="animate-pulse">
                      <td className="px-6 py-4"><div className="h-4 w-32 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-16 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-24 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-24 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-20 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4 text-right"><div className="h-4 w-12 bg-slate-800 rounded-md ml-auto" /></td>
                    </tr>
                  ))
                ) : campaigns.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-500">
                      <Megaphone className="w-8 h-8 mx-auto mb-2 text-slate-600" />
                      <p>No active calling campaigns found.</p>
                    </td>
                  </tr>
                ) : (
                  campaigns.map((camp) => (
                    <tr key={camp.id} className="hover:bg-slate-800/40 transition duration-150">
                      <td className="px-6 py-4 font-semibold text-slate-100">
                        {camp.name}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-medium border ${getStatusBadge(camp.status)}`}>
                          {camp.status}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="space-y-1">
                          <div className="flex justify-between text-[10px] text-slate-400 font-mono">
                            <span>{camp.completed_count + camp.skipped_count} / {camp.total_count} Calls</span>
                            <span>{Math.round(((camp.completed_count + camp.skipped_count) / (camp.total_count || 1)) * 100)}%</span>
                          </div>
                          <div className="w-32 h-1.5 bg-slate-800 rounded-full overflow-hidden flex">
                            <div
                              className="h-full bg-emerald-500"
                              style={{ width: `${(camp.completed_count / (camp.total_count || 1)) * 100}%` }}
                              title="Completed"
                            />
                            <div
                              className="h-full bg-sky-500"
                              style={{ width: `${(camp.skipped_count / (camp.total_count || 1)) * 100}%` }}
                              title="Skipped Opt Out"
                            />
                            <div
                              className="h-full bg-rose-500"
                              style={{ width: `${(camp.failed_count / (camp.total_count || 1)) * 100}%` }}
                              title="Failed"
                            />
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4 font-mono text-slate-300">
                        {camp.from_phone}
                      </td>
                      <td className="px-6 py-4 text-slate-400">
                        {new Date(camp.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-6 py-4 text-right space-x-2">
                        <button
                          onClick={() => handleViewTargets(camp)}
                          className="px-2.5 py-1 rounded-lg bg-slate-800 text-purple-300 hover:bg-slate-700 text-[11px]"
                          title="View target call details"
                        >
                          Targets
                        </button>

                        {camp.status === "running" && (
                          <button
                            onClick={() => handlePauseCampaign(camp.id)}
                            className="px-2.5 py-1 rounded-lg bg-sky-500/10 text-sky-300 border border-sky-500/20 hover:bg-sky-500/20 text-[11px]"
                          >
                            Pause
                          </button>
                        )}

                        {camp.status === "paused" && (
                          <button
                            onClick={() => handleResumeCampaign(camp.id)}
                            className="px-2.5 py-1 rounded-lg bg-purple-500/10 text-purple-300 border border-purple-500/20 hover:bg-purple-500/20 text-[11px]"
                          >
                            Resume
                          </button>
                        )}

                        {camp.failed_count > 0 && camp.status !== "running" && (
                          <button
                            onClick={() => handleRetryFailed(camp.id)}
                            className="px-2.5 py-1 rounded-lg bg-amber-500/10 text-amber-300 border border-amber-500/20 hover:bg-amber-500/20 text-[11px]"
                          >
                            Retry Failed
                          </button>
                        )}

                        {camp.status !== "cancelled" && camp.status !== "completed" && (
                          <button
                            onClick={() => setCancellingCampaignId(camp.id)}
                            className="px-2.5 py-1 rounded-lg bg-rose-500/10 text-rose-300 border border-rose-500/20 hover:bg-rose-500/20 text-[11px]"
                          >
                            Cancel
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Create Campaign Modal */}
        {showCreateModal && (
          <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
            <form
              onSubmit={handleCreateCampaign}
              className="bg-slate-900 border border-purple-900/40 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-base font-semibold text-slate-100">Create Outbound Campaign</h3>
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="text-slate-400 hover:text-slate-200"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Campaign Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Lead Qualification Q4"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Caller ID (From Phone)</label>
                <input
                  type="text"
                  required
                  value={formData.from_phone}
                  onChange={(e) => setFormData({ ...formData, from_phone: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div className="space-y-3 pt-1 border-t border-slate-800">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Select Target Contact List (Recommended)
                  </label>
                  <select
                    value={formData.contact_list_id}
                    onChange={(e) => setFormData({ ...formData, contact_list_id: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-purple-500"
                  >
                    <option value="">-- Or enter manual phone numbers below --</option>
                    {contactLists.map((lst) => (
                      <option key={lst.id} value={lst.id}>
                        {lst.name} ({lst.contact_count} contacts)
                      </option>
                    ))}
                  </select>
                </div>

                {!formData.contact_list_id && (
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Manual Target Phone Numbers (One per line)
                    </label>
                    <textarea
                      rows={3}
                      placeholder="+15550101&#10;+15550102&#10;+15550103"
                      value={formData.target_phones_input}
                      onChange={(e) => setFormData({ ...formData, target_phones_input: e.target.value })}
                      className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 font-mono focus:outline-none focus:border-purple-500"
                    />
                  </div>
                )}
              </div>

              <div className="flex justify-end space-x-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 rounded-xl bg-slate-800 text-slate-300 text-xs hover:bg-slate-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-xl bg-purple-600 text-white text-xs font-medium hover:bg-purple-500"
                >
                  Launch Campaign
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Campaign Targets Details Modal */}
        {selectedTargetsCampaign && (
          <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-purple-900/40 rounded-2xl max-w-2xl w-full p-6 space-y-4 shadow-2xl">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div>
                  <h3 className="text-base font-semibold text-slate-100">
                    Campaign Target Details
                  </h3>
                  <p className="text-xs text-slate-400 font-mono">
                    {selectedTargetsCampaign.name} &bull; {selectedTargetsCampaign.target_phones.length} Target Phone Records
                  </p>
                </div>
                <button
                  onClick={() => setSelectedTargetsCampaign(null)}
                  className="text-slate-400 hover:text-slate-200"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {targetsLoading ? (
                <div className="p-8 text-center text-xs text-slate-500 animate-pulse">
                  Loading target status records...
                </div>
              ) : (
                <div className="max-h-80 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-900 text-slate-400 uppercase font-mono text-[10px] border-b border-slate-800">
                      <tr>
                        <th className="px-4 py-3">Phone Number</th>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3">Attempts</th>
                        <th className="px-4 py-3">Last Error / Result</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                      {campaignTargets.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="px-4 py-6 text-center text-slate-500">
                            No target execution records initialized yet.
                          </td>
                        </tr>
                      ) : (
                        campaignTargets.map((tgt) => (
                          <tr key={tgt.id}>
                            <td className="px-4 py-2.5 text-slate-200">{tgt.phone_number}</td>
                            <td className="px-4 py-2.5">
                              <span className={`px-2 py-0.5 rounded-full border text-[10px] ${getTargetStatusBadge(tgt.status)}`}>
                                {tgt.status}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-slate-400">{tgt.attempts} / {tgt.max_retries}</td>
                            <td className="px-4 py-2.5 text-slate-400 truncate max-w-xs">{tgt.last_error || "—"}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="flex justify-end pt-2">
                <button
                  onClick={() => setSelectedTargetsCampaign(null)}
                  className="px-4 py-2 rounded-xl bg-slate-800 text-slate-300 text-xs hover:bg-slate-700"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Confirmation Modal for Cancellation */}
        {cancellingCampaignId && (
          <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-rose-900/40 rounded-2xl max-w-sm w-full p-6 space-y-4">
              <h3 className="text-base font-semibold text-slate-100">Cancel Campaign?</h3>
              <p className="text-xs text-slate-400">
                Are you sure you want to cancel this campaign? Pending outbound calls will be halted immediately.
              </p>
              <div className="flex justify-end space-x-3">
                <button
                  onClick={() => setCancellingCampaignId(null)}
                  className="px-3.5 py-2 rounded-xl bg-slate-800 text-slate-300 text-xs"
                >
                  Go Back
                </button>
                <button
                  onClick={() => handleCancelCampaign(cancellingCampaignId)}
                  className="px-3.5 py-2 rounded-xl bg-rose-600 text-white text-xs font-medium"
                >
                  Yes, Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
