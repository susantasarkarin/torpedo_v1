/**
 * Panel Rewards Page
 * Displays rewards balance, history, and redemption options
 */

import { useState } from 'react';
import { useRewards } from '../hooks/useRewards';
import '../styles/panel.css';

export default function PanelRewards() {
  const { balance, history, loading, error, refetch } = useRewards();
  const [activeTab, setActiveTab] = useState('history');

  const formatDate = (dateStr) => {
    try {
      return new Date(dateStr).toLocaleDateString('en-IN', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      {/* Balance Card */}
      <div className="bg-gradient-to-r from-panel-primary to-panel-primary-600 rounded-xl p-6 mb-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-white/70 text-sm mb-1">Available Balance</p>
            <p className="text-4xl font-bold">
              ₹{balance.balance?.toFixed(2) || '0.00'}
            </p>
            {balance.pending > 0 && (
              <p className="text-white/70 text-sm mt-2">
                + ₹{balance.pending.toFixed(2)} pending
              </p>
            )}
          </div>
          <div className="text-right">
            <button className="panel-btn-accent">
              Redeem Points
            </button>
            <p className="text-white/60 text-xs mt-2">
              Min. ₹100 to redeem
            </p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100">
        <div className="flex border-b border-gray-100">
          <button
            className={`flex-1 py-4 text-center font-medium transition-colors ${
              activeTab === 'history'
                ? 'text-panel-primary border-b-2 border-panel-primary'
                : 'text-gray-500 hover:text-gray-700'
            }`}
            onClick={() => setActiveTab('history')}
          >
            Transaction History
          </button>
          <button
            className={`flex-1 py-4 text-center font-medium transition-colors ${
              activeTab === 'redeem'
                ? 'text-panel-primary border-b-2 border-panel-primary'
                : 'text-gray-500 hover:text-gray-700'
            }`}
            onClick={() => setActiveTab('redeem')}
          >
            Redeem Rewards
          </button>
        </div>

        <div className="p-6">
          {activeTab === 'history' ? (
            /* Transaction History */
            loading ? (
              <div className="space-y-4">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="animate-pulse h-16 bg-gray-100 rounded"></div>
                ))}
              </div>
            ) : history.length === 0 ? (
              <div className="panel-empty-state">
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <h3 className="text-lg font-medium text-gray-800 mb-1">No Transactions Yet</h3>
                <p className="text-gray-500">
                  Complete surveys to start earning rewards!
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {history.map((tx) => (
                  <div
                    key={tx.id}
                    className="flex items-center justify-between p-4 bg-gray-50 rounded-lg"
                  >
                    <div className="flex items-center gap-4">
                      <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                        tx.type === 'earned' ? 'bg-green-100' : 'bg-red-100'
                      }`}>
                        {tx.type === 'earned' ? (
                          <svg className="w-5 h-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
                          </svg>
                        )}
                      </div>
                      <div>
                        <p className="font-medium text-gray-800">{tx.description}</p>
                        <p className="text-sm text-gray-500">{formatDate(tx.date)}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className={`font-bold ${tx.type === 'earned' ? 'text-green-600' : 'text-red-600'}`}>
                        {tx.type === 'earned' ? '+' : '-'}₹{tx.amount.toFixed(2)}
                      </p>
                      <p className={`text-xs ${
                        tx.status === 'completed' ? 'text-gray-500' : 'text-yellow-600'
                      }`}>
                        {tx.status}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )
          ) : (
            /* Redeem Options */
            <div>
              <h3 className="text-lg font-medium text-gray-800 mb-4">Available Rewards</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Amazon Gift Card */}
                <div className="border border-gray-200 rounded-lg p-4 hover:border-panel-primary transition-colors cursor-pointer">
                  <div className="flex items-center gap-4">
                    <div className="w-16 h-16 bg-orange-100 rounded-lg flex items-center justify-center">
                      <span className="text-2xl">🎁</span>
                    </div>
                    <div>
                      <p className="font-medium text-gray-800">Amazon Gift Card</p>
                      <p className="text-sm text-gray-500">Starting from ₹100</p>
                    </div>
                  </div>
                </div>

                {/* Flipkart Gift Card */}
                <div className="border border-gray-200 rounded-lg p-4 hover:border-panel-primary transition-colors cursor-pointer">
                  <div className="flex items-center gap-4">
                    <div className="w-16 h-16 bg-blue-100 rounded-lg flex items-center justify-center">
                      <span className="text-2xl">🛒</span>
                    </div>
                    <div>
                      <p className="font-medium text-gray-800">Flipkart Gift Card</p>
                      <p className="text-sm text-gray-500">Starting from ₹100</p>
                    </div>
                  </div>
                </div>

                {/* PayPal */}
                <div className="border border-gray-200 rounded-lg p-4 hover:border-panel-primary transition-colors cursor-pointer">
                  <div className="flex items-center gap-4">
                    <div className="w-16 h-16 bg-indigo-100 rounded-lg flex items-center justify-center">
                      <span className="text-2xl">💳</span>
                    </div>
                    <div>
                      <p className="font-medium text-gray-800">PayPal Transfer</p>
                      <p className="text-sm text-gray-500">Starting from ₹500</p>
                    </div>
                  </div>
                </div>

                {/* UPI Transfer */}
                <div className="border border-gray-200 rounded-lg p-4 hover:border-panel-primary transition-colors cursor-pointer">
                  <div className="flex items-center gap-4">
                    <div className="w-16 h-16 bg-green-100 rounded-lg flex items-center justify-center">
                      <span className="text-2xl">📱</span>
                    </div>
                    <div>
                      <p className="font-medium text-gray-800">UPI Transfer</p>
                      <p className="text-sm text-gray-500">Starting from ₹100</p>
                    </div>
                  </div>
                </div>
              </div>

              <p className="mt-6 text-sm text-gray-500 text-center">
                Redemption requests are processed within 3-5 business days.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
